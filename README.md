# AccessiLearn

Turns visual learning material — textbook chapters, diagrams, photos of
experiments, video-scene descriptions — into podcast-style narrated audio
for blind and low-vision learners, with a fully accessible, cursor/focus
voice-guided frontend.

## How it maps to the research brief

| Brief requirement | Where it lives |
|---|---|
| Convert textbook chapters into podcast-style lessons | `POST /api/generate-script` (mode="textbook") in `backend/main.py` |
| Rewrite formulas, diagrams, experiments into spoken language | `SCRIPT_SYSTEM_PROMPT` — explicit rules for reading equations aloud, describing diagrams fully, narrating experiments step by step |
| Turn video/real-world scenes into narration | `POST /api/describe-image` (Claude vision) feeds into `generate-script` with mode="diagram"/"video" |
| Digitize/curate source materials | `POST /api/extract-pdf` (pulls chapter text out of a PDF) |
| Run and log AI pipelines (LLM, speech, TTS) | `backend/main.py` — Claude for rewriting + vision, gTTS for speech; every call is a discrete, loggable step |
| Prepare audio for evaluation by educators/listeners | MP3 output + full transcript, downloadable from the UI |
| UI usable by visually impaired users | High-contrast theme, large adjustable text, full keyboard nav, strong focus rings, and a **cursor/focus-guided voice narrator** (see below) |

## The cursor-guided voice idea, implemented

Every interactive/informational element in `frontend/index.html` has a
`data-speak="..."` attribute. `frontend/app.js`'s `VoiceGuide` module listens
for `mousemove` and `focusin` events, finds the nearest `[data-speak]`
ancestor, and speaks its label via the browser's built-in
`speechSynthesis` API (debounced so fast mouse movement doesn't cause
overlapping speech). So moving the cursor onto "Home" (or any button/field)
speaks its name aloud, exactly like the brief's example. It's a toggle in
the header, off by default is easy to change, and it's independent from
(and won't fight with) a real screen reader like NVDA/JAWS/VoiceOver.

## Architecture

```
Browser (frontend/)                FastAPI backend (backend/)
┌─────────────────────┐            ┌───────────────────────────┐
│ index.html/app.js    │  fetch()   │ /api/extract-pdf   (pypdf)│
│ - tabs: text/PDF/img │ ─────────► │ /api/describe-image (Claude vision)│
│ - VoiceGuide (cursor  │            │ /api/generate-script (Claude)│
│   + focus narration)  │ ◄───────── │ /api/generate-audio  (gTTS)│
│ - audio player         │  json/mp3 │ /api/pipeline/textbook (all-in-one)│
└─────────────────────┘            └───────────────────────────┘
```

## Prerequisites

- **Python 3.10+**
- An **Anthropic API key** (https://console.anthropic.com) — used for the
  script-rewriting and image-description steps
- A modern browser (Chrome, Edge, Firefox, Safari) — used for
  `speechSynthesis` (cursor voice guide) and audio playback
- No Node.js/build step needed — the frontend is plain HTML/CSS/JS

## Setup

```bash
# 1. Backend
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# edit .env and paste your ANTHROPIC_API_KEY

uvicorn main:app --reload --port 8000
```

```bash
# 2. Frontend (separate terminal) — any static server works
cd frontend
python -m http.server 5500
# open http://localhost:5500 in your browser
```

If you serve the frontend from a different origin/port, update `API_BASE`
at the top of `frontend/app.js`.

## API reference (for logging/evaluation tooling)

- `GET  /api/health` — check server + LLM key status
- `POST /api/extract-pdf` — multipart `file` → `{ text }`
- `POST /api/describe-image` — multipart `file` → `{ description }`
- `POST /api/generate-script` — form `source_text, topic_title, mode` → `{ script }`
- `POST /api/generate-audio` — form `script` → `{ audio_url, chunks }`
- `POST /api/pipeline/textbook` — form `source_text, topic_title` → full script + audio in one call (handy for batch-processing many chapters and logging results)

## Running it completely free (no API key, no cost)

`backend/main_ollama.py` is a drop-in replacement for `main.py` — same
endpoints, same request/response shape, so the frontend doesn't need any
changes. It uses [Ollama](https://ollama.com) to run an LLM **locally on
your own machine** instead of calling the Anthropic API.

```bash
# 1. Install Ollama: https://ollama.com/download (Windows/Mac/Linux)

# 2. Pull a text model and a vision model (one-time download, then free forever)
ollama pull llama3.1     # ~4.7GB - script rewriting (mistral or gemma2 also work)
ollama pull llava        # ~4.5GB - describes diagrams/photos

# 3. Ollama runs a local server automatically (localhost:11434).
#    If it's not running: `ollama serve`

# 4. Start the free backend instead of main.py
cd backend
pip install -r requirements.txt
uvicorn main_ollama:app --reload --port 8000
```

Then run the frontend exactly as before (`python -m http.server 5500`) —
no changes needed there.

**Trade-offs to know about:**
- Needs a reasonably capable machine (8GB+ RAM minimum for a 7-8B model; a GPU makes it much faster, CPU-only still works but is slower)
- Quality is good but a notch below Claude for nuanced rewriting of dense academic text — worth spot-checking a few chapters before a full evaluation run
- Fully offline after the initial model download — handy if you're processing sensitive or large volumes of material

**If your machine can't run a local model**, the next-cheapest options are
a free-tier cloud API — Google Gemini (aistudio.google.com) or Groq
(console.groq.com) both have generous free quotas and a similar
`system prompt + user message` API shape, so `main.py`'s `generate_script`/
`describe_image` functions would need only minor edits to point at their
endpoints instead of Anthropic's.

## Swapping in a higher-quality TTS voice

`gTTS` is free and needs no key, which is why it's the default here, but it
has limited voice control. For a stronger evaluation with educators/listeners,
swap the `generate_audio` function in `backend/main.py` for:
- **Azure Speech** or **AWS Polly** — natural Indian-English neural voices, SSML control over pacing/emphasis (useful for slowing down for formulas)
- **ElevenLabs** — very natural voices, supports custom pacing

The rest of the pipeline (script generation, chunking, API contract) stays
the same — only the body of `generate_audio()` needs to change.

## Suggested next steps for the research project

1. **Logging**: wrap each pipeline call in `main.py` with structured logs (input length, model, latency, token usage) for the evaluation study.
2. **Batch mode**: loop `/api/pipeline/textbook` over a folder of chapter PDFs to digitize a whole textbook.
3. **Evaluation harness**: a simple form (or Google Form) where blind/low-vision testers rate clarity, pacing, and completeness of each generated lesson — feed low scores back into prompt iteration.
4. **SSML/pacing control**: once on Polly/Azure, add pauses before/after formula narration so listeners have processing time.
