"""
AccessiLearn backend — GEMINI (FREE TIER) VERSION
---------------------------------------------------
Same pipeline and same API contract as main.py, but uses Google's Gemini
API (generous free tier, no credit card required to start) instead of the
Anthropic API for script rewriting and image description. gTTS (already
free) still handles text-to-speech.

Get a free API key: https://aistudio.google.com/app/apikey

Run:
  pip install -r requirements.txt
  cp .env.example .env      # paste your GEMINI_API_KEY
  uvicorn main_gemini:app --reload --port 8000
"""

import os
import re
import uuid
from pathlib import Path

from google import genai
from google.genai import types
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from gtts import gTTS
from PIL import Image
import io
from pypdf import PdfReader

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TEXT_MODEL_NAME = os.getenv("GEMINI_TEXT_MODEL", "gemini-3.6-flash")
VISION_MODEL_NAME = os.getenv("GEMINI_VISION_MODEL", "gemini-3.6-flash")  # same model handles both

TTS_LANG = os.getenv("TTS_LANG", "en")
TTS_TLD = os.getenv("TTS_TLD", "co.in")

AUDIO_DIR = Path(__file__).parent / "audio_output"
AUDIO_DIR.mkdir(exist_ok=True)

client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

app = FastAPI(title="AccessiLearn API (Gemini free tier)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/audio", StaticFiles(directory=str(AUDIO_DIR)), name="audio")

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
6. Keep sentences short enough to be easy to follow by ear alone.
7. Output ONLY the narration text - no headings, no markdown, no notes to \
   yourself, nothing but what should be spoken aloud.
8. Keep the tone encouraging and human, never robotic or dry.
"""

IMAGE_DESCRIBE_PROMPT = """You are describing an educational image (a diagram, chart, \
graph, photo of an experiment, or a video frame) for a blind or low-vision \
student. Describe fully and precisely what is shown, including labels, \
spatial layout, colors if pedagogically relevant, and any text visible in \
the image. Be thorough - this description is the ONLY way this student can \
access the visual content. Do not speculate about things you cannot see. \
Write it as plain descriptive prose (not a script yet)."""


def require_key():
    if not GEMINI_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="GEMINI_API_KEY is not set on the server. Add it to backend/.env",
        )


def chunk_text_for_tts(text: str, max_chars: int = 4500):
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


# ---------------------------------------------------------------------------
# Routes — same paths/contract as main.py, so the frontend needs no changes
# ---------------------------------------------------------------------------


@app.get("/api/health")
def health():
    return {"status": "ok", "llm_configured": GEMINI_API_KEY is not None}


@app.post("/api/extract-pdf")
async def extract_pdf(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Please upload a .pdf file")
    reader = PdfReader(file.file)
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    if not text.strip():
        raise HTTPException(422, "Couldn't find selectable text in this PDF (it may be a scan).")
    return {"text": text}


@app.post("/api/describe-image")
async def describe_image(file: UploadFile = File(...)):
    require_key()
    img_bytes = await file.read()
    image = Image.open(io.BytesIO(img_bytes))

    try:
        resp = client.models.generate_content(
            model=VISION_MODEL_NAME,
            contents=[IMAGE_DESCRIBE_PROMPT, image],
        )
    except Exception as e:
        raise HTTPException(502, f"Gemini vision call failed: {e}")

    return {"description": resp.text}


@app.post("/api/generate-script")
async def generate_script(
    source_text: str = Form(...),
    topic_title: str = Form(default=""),
    mode: str = Form(default="textbook"),
):
    require_key()

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

    try:
        resp = client.models.generate_content(
            model=TEXT_MODEL_NAME,
            contents=user_prompt,
            config=types.GenerateContentConfig(system_instruction=SCRIPT_SYSTEM_PROMPT),
        )
    except Exception as e:
        raise HTTPException(502, f"Gemini text call failed: {e}")

    return {"script": resp.text}


@app.post("/api/generate-audio")
async def generate_audio(script: str = Form(...)):
    if not script.strip():
        raise HTTPException(400, "Script text is empty")

    file_id = f"{uuid.uuid4().hex}.mp3"
    out_path = AUDIO_DIR / file_id

    chunks = chunk_text_for_tts(script)
    if len(chunks) == 1:
        gTTS(text=chunks[0], lang=TTS_LANG, tld=TTS_TLD, slow=False).save(str(out_path))
    else:
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
    script_resp = await generate_script(source_text=source_text, topic_title=topic_title, mode="textbook")
    audio_resp = await generate_audio(script=script_resp["script"])
    return {**script_resp, **audio_resp}
