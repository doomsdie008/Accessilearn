"""
AccessiLearn backend — FREE / LOCAL VERSION
--------------------------------------------
Identical pipeline and API contract to main.py, but uses a locally-running
Ollama model instead of the Anthropic API for script rewriting and image
description. Zero per-call cost, no API key, works offline once models are
pulled. gTTS (already free) still handles text-to-speech.

Requires Ollama installed and running locally: https://ollama.com

Setup:
  # 1. Install Ollama (see https://ollama.com/download)
  # 2. Pull a text model and a vision model:
  ollama pull llama3.1          # text rewriting (or: mistral, gemma2)
  ollama pull llava             # image description (vision)
  # 3. Make sure Ollama is running (it starts a local server on :11434
  #    automatically after install, or run `ollama serve`)

Run:
  pip install -r requirements.txt
  uvicorn main_ollama:app --reload --port 8000
"""

import base64
import os
import re
import uuid
from pathlib import Path

import requests
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from gtts import gTTS
from pypdf import PdfReader

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
TEXT_MODEL = os.getenv("OLLAMA_TEXT_MODEL", "llama3.1")
VISION_MODEL = os.getenv("OLLAMA_VISION_MODEL", "llava")

TTS_LANG = os.getenv("TTS_LANG", "en")
TTS_TLD = os.getenv("TTS_TLD", "co.in")

AUDIO_DIR = Path(__file__).parent / "audio_output"
AUDIO_DIR.mkdir(exist_ok=True)

app = FastAPI(title="AccessiLearn API (Free / Local)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/audio", StaticFiles(directory=str(AUDIO_DIR)), name="audio")

# ---------------------------------------------------------------------------
# Prompting — same rules as the Claude version, adapted for a local model
# ---------------------------------------------------------------------------

SCRIPT_SYSTEM_PROMPT = """You are an expert accessibility educator who converts visual \
learning material into engaging, podcast-style audio scripts for blind and \
low-vision students in India.

Rules for the script you write:
1. Write it exactly as it should be SPOKEN aloud by a narrator - warm, clear, \
   conversational, like a good educational podcast host.
2. NEVER include visual-only references like "as shown below" or "see Figure 2". \
   Instead, fully describe what any diagram, graph, chart, or experiment shows.
3. Read mathematical formulas and equations out in full plain speech \
   (e.g. "x squared plus two x minus three equals zero"). Never use symbols, \
   LaTeX, or notation in the output - only words.
4. Break long topics into short, clearly signposted segments \
   ("First, ...", "Next, ...", "Finally, ...").
5. For experiments/procedures, narrate them like a step-by-step story.
6. Keep sentences short and easy to follow by ear alone.
7. Output ONLY the narration text - no headings, no markdown, no notes to \
   yourself, nothing but what should be spoken aloud.
8. Keep the tone encouraging and human, never robotic or dry.
"""

IMAGE_DESCRIBE_PROMPT = """Describe this educational image (a diagram, chart, graph, \
photo of an experiment, or video frame) for a blind or low-vision student. \
Describe fully and precisely what is shown, including labels, spatial layout, \
and any visible text. Be thorough - this description is the only way this \
student can access the visual content. Write it as plain descriptive prose."""


def ollama_generate(prompt: str, system: str = "", model: str = TEXT_MODEL) -> str:
    """Call a local Ollama model's /api/generate endpoint (non-streaming)."""
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "system": system,
                "stream": False,
            },
            timeout=300,
        )
        resp.raise_for_status()
    except requests.exceptions.ConnectionError:
        raise HTTPException(
            status_code=503,
            detail=(
                f"Couldn't reach Ollama at {OLLAMA_URL}. Is it installed and "
                f"running? Try `ollama serve`, and make sure you've pulled "
                f"'{model}' with `ollama pull {model}`."
            ),
        )
    return resp.json().get("response", "").strip()


def ollama_describe_image(img_b64: str) -> str:
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": VISION_MODEL,
                "prompt": IMAGE_DESCRIBE_PROMPT,
                "images": [img_b64],
                "stream": False,
            },
            timeout=300,
        )
        resp.raise_for_status()
    except requests.exceptions.ConnectionError:
        raise HTTPException(
            status_code=503,
            detail=f"Couldn't reach Ollama at {OLLAMA_URL} for vision model '{VISION_MODEL}'.",
        )
    return resp.json().get("response", "").strip()


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
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        models = [m["name"] for m in r.json().get("models", [])]
        return {"status": "ok", "ollama_running": True, "models_available": models}
    except Exception:
        return {"status": "ok", "ollama_running": False, "models_available": []}


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
    img_bytes = await file.read()
    b64 = base64.b64encode(img_bytes).decode("utf-8")
    description = ollama_describe_image(b64)
    return {"description": description}


@app.post("/api/generate-script")
async def generate_script(
    source_text: str = Form(...),
    topic_title: str = Form(default=""),
    mode: str = Form(default="textbook"),
):
    mode_hint = {
        "textbook": "This source is a textbook chapter excerpt.",
        "video": "This source is a description of a video's visual content and any on-screen text.",
        "diagram": "This source is a description of a diagram, chart, or experiment.",
    }.get(mode, "This is educational source material.")

    prompt = f"""{mode_hint}

Topic title: {topic_title or "(untitled)"}

SOURCE MATERIAL:
---
{source_text}
---

Rewrite this into a complete podcast-style narration script following your \
system instructions. Don't truncate or summarize away important content."""

    script = ollama_generate(prompt, system=SCRIPT_SYSTEM_PROMPT, model=TEXT_MODEL)
    return {"script": script}


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
