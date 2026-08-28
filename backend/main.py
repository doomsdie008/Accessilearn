"""
AccessiLearn backend
---------------------
Turns visual learning material (textbook text, PDF chapters, or descriptions
of diagrams/videos/scenes) into podcast-style narrated audio for blind and
low-vision learners.

Pipeline:
  1. Ingest       -> raw text, uploaded PDF, or uploaded image
  2. Understand   -> (for images) Claude vision describes the diagram/scene
  3. Rewrite      -> Claude rewrites content into warm, spoken, podcast-style
                      narration (formulas/diagrams/experiments -> plain speech)
  4. Voice        -> gTTS renders the script to an MP3
  5. Serve        -> audio file + full transcript returned to the frontend

Run:
  pip install -r requirements.txt
  cp .env.example .env   # add your ANTHROPIC_API_KEY
  uvicorn main:app --reload --port 8000
"""

import base64
import os
import re
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from gtts import gTTS
from pypdf import PdfReader

import anthropic

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
TTS_LANG = os.getenv("TTS_LANG", "en")
TTS_TLD = os.getenv("TTS_TLD", "co.in")  # co.in gives an Indian-English accent

AUDIO_DIR = Path(__file__).parent / "audio_output"
AUDIO_DIR.mkdir(exist_ok=True)

app = FastAPI(title="AccessiLearn API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/audio", StaticFiles(directory=str(AUDIO_DIR)), name="audio")

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

MODEL = "claude-sonnet-4-6"

# ---------------------------------------------------------------------------
# Prompting
# ---------------------------------------------------------------------------

SCRIPT_SYSTEM_PROMPT = """You are an expert accessibility educator who converts visual \
learning material into engaging, podcast-style audio scripts for blind and \
low-vision students in India.

Rules for the script you write:
1. Write it exactly as it should be SPOKEN aloud by a narrator - warm, clear, \
   conversational, like a good educational podcast host (e.g. "Let's take a \
   look at...", "Picture this...", "Now here's the interesting part...").
2. NEVER include visual-only references like "as shown below", "see Figure 2", \
   or "in the image above". Instead, fully describe what the diagram, graph, \
   chart, or experiment shows, step by step, so a listener who cannot see it \
   still understands it completely.
3. Read mathematical formulas and equations out in full plain speech \
   (e.g. "x squared plus two x minus three equals zero", not "x^2+2x-3=0"). \
   Never use symbols, LaTeX, or notation in the output - only words.
4. Break long or complex topics into short, clearly signposted segments \
   ("First, ...", "Next, ...", "Finally, ..."), and briefly restate the key \
   takeaway at the end of each segment.
5. For experiments/procedures, narrate them like a step-by-step story: what \
   materials are used, what happens, and why it happens.
6. Keep sentences short enough to be easy to follow by ear alone - avoid \
   dense, multi-clause academic sentences.
7. Do not add headings, bullet points, markdown, or any text that only makes \
   sense visually - output must be pure narration text, nothing else.
8. Keep the tone encouraging and human, never robotic or dry.
"""

IMAGE_DESCRIBE_SYSTEM_PROMPT = """You are describing an educational image (a diagram, \
chart, graph, photo of an experiment, or a video frame) for a blind or \
low-vision student. Describe fully and precisely what is shown, including \
labels, spatial layout, colors if pedagogically relevant, and any text \
visible in the image. Be thorough - this description is the ONLY way this \
student can access the visual content. Do not speculate about things you \
cannot see. Write it as plain descriptive prose (not a script yet)."""


def chunk_text_for_tts(text: str, max_chars: int = 4500):
    """gTTS has practical limits on very long single calls; split on
    sentence boundaries so audio stays under those limits and stitches
    together naturally."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks, current = [], ""
    for s in sentences:
        if len(current) + len(s) + 1 > max_chars:
            chunks.append(current.strip())
            current = s
        else:
            current += " " + s
    if current.strip():
        chunks.append(current.strip())
    return chunks


def require_client():
    if client is None:
        raise HTTPException(
            status_code=500,
            detail="ANTHROPIC_API_KEY is not set on the server. Add it to backend/.env",
        )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/api/health")
def health():
    return {"status": "ok", "llm_configured": client is not None}


@app.post("/api/extract-pdf")
async def extract_pdf(file: UploadFile = File(...)):
    """Pull raw text out of an uploaded textbook chapter PDF."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Please upload a .pdf file")
    reader = PdfReader(file.file)
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    if not text.strip():
        raise HTTPException(
            422, "Couldn't find selectable text in this PDF (it may be a scan)."
        )
    return {"text": text}


@app.post("/api/describe-image")
async def describe_image(file: UploadFile = File(...)):
    """Use Claude vision to turn a diagram/photo/video-frame into a rich
    text description that a downstream script-writer can narrate."""
    require_client()
    img_bytes = await file.read()
    media_type = file.content_type or "image/png"
    b64 = base64.b64encode(img_bytes).decode("utf-8")

    resp = client.messages.create(
        model=MODEL,
        max_tokens=1000,
        system=IMAGE_DESCRIBE_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": b64},
                    },
                    {
                        "type": "text",
                        "text": "Describe this educational image for a blind student.",
                    },
                ],
            }
        ],
    )
    description = "".join(b.text for b in resp.content if b.type == "text")
    return {"description": description}


@app.post("/api/generate-script")
async def generate_script(
    source_text: str = Form(...),
    topic_title: str = Form(default=""),
    mode: str = Form(default="textbook"),  # "textbook" | "video" | "diagram"
):
    """Rewrite raw source material into a podcast-style narration script."""
    require_client()

    mode_hint = {
        "textbook": "This source is a textbook chapter excerpt.",
        "video": "This source is a description of a video's visual content and any on-screen text.",
        "diagram": "This source is a description of a diagram, chart, or experiment.",
    }.get(mode, "This is educational source material.")

    user_prompt = f"""{mode_hint}

Topic title: {topic_title or "(untitled)"}

SOURCE MATERIAL:
---
{source_text}
---

Rewrite this into a complete podcast-style narration script following your \
system instructions. Aim for a natural, complete lesson - don't truncate or \
summarize away important content, just make it fully listenable."""

    resp = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SCRIPT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    script = "".join(b.text for b in resp.content if b.type == "text")
    return {"script": script}


@app.post("/api/generate-audio")
async def generate_audio(script: str = Form(...)):
    """Render a narration script to speech and save it as an MP3."""
    if not script.strip():
        raise HTTPException(400, "Script text is empty")

    file_id = f"{uuid.uuid4().hex}.mp3"
    out_path = AUDIO_DIR / file_id

    chunks = chunk_text_for_tts(script)
    if len(chunks) == 1:
        tts = gTTS(text=chunks[0], lang=TTS_LANG, tld=TTS_TLD, slow=False)
        tts.save(str(out_path))
    else:
        # Synthesize each chunk, then concatenate the raw mp3 byte streams
        # (mp3 frame concatenation works fine for playback purposes here).
        with open(out_path, "wb") as out_f:
            for chunk in chunks:
                tmp_path = AUDIO_DIR / f"_tmp_{uuid.uuid4().hex}.mp3"
                gTTS(text=chunk, lang=TTS_LANG, tld=TTS_TLD, slow=False).save(str(tmp_path))
                out_f.write(tmp_path.read_bytes())
                tmp_path.unlink()

    return {"audio_url": f"/audio/{file_id}", "chunks": len(chunks)}


@app.post("/api/pipeline/textbook")
async def full_textbook_pipeline(
    source_text: str = Form(...),
    topic_title: str = Form(default=""),
):
    """Convenience endpoint: text in -> podcast script + audio out, in one call."""
    script_resp = await generate_script(source_text=source_text, topic_title=topic_title, mode="textbook")
    audio_resp = await generate_audio(script=script_resp["script"])
    return {**script_resp, **audio_resp}
