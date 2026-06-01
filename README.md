# SpeechifyPDF

SpeechifyPDF seamlessly transforms your PDF documents into natural, high-quality spoken audio. Perfect for commuters, multi-taskers, and auditory learners, our app accurately extracts text and leverages advanced Text-to-Speech technology to bring your files to life. Experience a more accessible, convenient way to consume written content anywhere.

A single-app PDF reader powered by **FastAPI** and the **Kokoro TTS model**, with real-time word-level highlighting as it reads aloud. Built for **CPU-only systems** with per-sentence streaming for responsive playback.

## Features

- 🎤 **High-quality TTS**: Synthesizes from PDFs using [Kokoro](https://github.com/hexgrad/kokoro) — a lightweight 82M-param model
- 🎯 **Per-word highlighting**: Each word lights up as the model speaks it
- ⚡ **CPU-optimized**: Streams one sentence at a time; prefetches ahead for gap-free playback
- 🎨 **Modern dark UI**: Sleek design with glassmorphism, ambient glows, and smooth animations
- 🎛️ **Voice & speed controls**: Multiple voices across US English, UK English; adjustable playback speed (0.5× – 1.75×)
- 📄 **Reflowed text**: PDFs are extracted and reflowed for easy reading
- 🖥️ **Single app**: FastAPI serves both the API and the frontend — one process, one port

## Quick Start (beginner-friendly)

No prior experience needed. The whole thing runs locally — no API keys, no cloud, no payment.

### What you need first

1. **A computer** running Linux, macOS, or Windows with about **8 GB of RAM**. Any
   modern CPU works — no graphics card required.
2. **Miniconda** (a free tool that manages Python versions for you). If you don't
   have it, download and install it from
   <https://www.anaconda.com/download/success> (pick "Miniconda"). After installing,
   **close and reopen your terminal** so the `conda` command becomes available.
   - Quick check: type `conda --version` and press Enter. If it prints a version
     number, you're good.
3. **An internet connection for the first run only** — the voice model (~350 MB) is
   downloaded automatically the first time you read a PDF, then cached forever.

> Why Miniconda? SpeechifyPDF needs Python 3.10–3.12 (the Kokoro voice model does
> **not** support Python 3.13 yet). Conda installs the right Python version in an
> isolated "environment" so it never interferes with anything else on your machine.

### Step 1 — Open a terminal in the project folder

```bash
cd SpeechifyPDF
```

### Step 2 — Create the environment and install everything (one time only)

Copy-paste these four lines one at a time:

```bash
conda create -n speechifyPDF python=3.12 -y      # make an isolated Python 3.12
conda activate speechifyPDF                       # switch into it
pip install torch --index-url https://download.pytorch.org/whl/cpu   # CPU version of PyTorch
pip install -r backend/requirements.txt           # the rest of the dependencies
```

This may take a few minutes. It only has to be done once.

### Step 3 — Start the app

**On Linux/macOS:**
```bash
./run.sh
```
(If you get a "permission denied" message, run `bash run.sh` instead.)

**On Windows:** double-click `run.bat`, or in a terminal run:
```bat
run.bat
```

When it's ready you'll see a line like:

```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

### Step 4 — Open it in your browser

Go to **<http://127.0.0.1:8000>**. Drag a PDF onto the page (or click to choose one),
then press the **Space** bar — or click any sentence — to start listening. Each word
lights up as it's read.

> **First read is slower.** The very first sentence triggers a one-time model
> download and warm-up, so it can take 10–30 seconds. After that, sentences are
> synthesized in a few seconds and cached for instant replay.

### Step 5 — Stop the app

Go back to the terminal and press **Ctrl + C**.

### Next time

You only do Step 2 once. To run the app again later:

```bash
cd SpeechifyPDF
conda activate speechifyPDF   # run.sh does this for you, so this line is optional
./run.sh
```

---

**Prefer to run it manually instead of the script?**
```bash
conda activate speechifyPDF
cd backend
uvicorn app:app --host 127.0.0.1 --port 8000
# then visit http://127.0.0.1:8000
```

## How It Works

### Backend (Python, FastAPI)

1. **PDF Extraction** (`pdf_utils.py`): Extracts text, filters non-printable characters, splits into sentences (~280 chars max for responsiveness).
2. **TTS** (`tts.py`): Uses Kokoro's `KPipeline` to synthesize each sentence, returning per-word timings (`start_ts`, `end_ts`).
3. **API** (`app.py`): Serves endpoints:
   - `POST /api/upload` → parses PDF, returns document structure
   - `GET /api/voices` → available TTS voices
   - `GET /api/tts/{doc_id}/{sentence_id}` → returns audio (base64 WAV) + word timings
4. **Static files**: FastAPI serves the frontend from `backend/static/`.

### Frontend (Vanilla HTML/CSS/JS)

1. **Upload**: Drag-and-drop or click to upload a PDF. Document text appears immediately.
2. **Playback**: Click a sentence or press **Space** to start reading. Click any word to seek within that sentence.
3. **Highlighting**: A `rAF` loop maps `<audio>.currentTime` to the active word, updating the highlight in real-time.
4. **Prefetch**: While a sentence plays, the next is fetched in the background for gap-free playback.

## Architecture

```
SpeechifyPDF/
├── backend/
│   ├── app.py             # FastAPI server + endpoints + static file serving
│   ├── pdf_utils.py       # PDF extraction & sentence splitting
│   ├── tts.py             # Kokoro pipeline wrapper
│   ├── requirements.txt
│   └── static/
│       ├── index.html     # Landing page + reader UI
│       ├── styles.css     # Dark theme styling
│       └── app.js         # Upload, playback, word highlighting logic
├── run.sh                 # Linux/macOS launcher
├── run.bat                # Windows launcher
└── README.md
```

### Key Design Decisions

- **Single app**: No separate frontend build step — FastAPI serves static HTML/CSS/JS directly alongside the API.
- **Per-sentence streaming**: Synthesis is CPU-bound; generating one sentence at a time keeps the UI responsive.
- **Reflowed text**: PDFs are extracted as plain text, avoiding layout complexity. Paragraphs and sentences are preserved.
- **Token-based alignment**: Kokoro tokens are grouped into display words (e.g., `"dog"` + `"."` → `"dog."`) using `whitespace` metadata.
- **Single audio element**: A shared `<audio>` element cycles through sentences; the rAF loop syncs highlighting to `currentTime`.
- **Caching**: Generated audio is cached in-memory (LRU on max documents), making replays instant.

## Usage Tips

- **Keyboard**: `Space` = play/pause | `←` / `→` = prev/next sentence
- **Click to seek**: Click any sentence to jump there; click a word to seek within the active sentence
- **Auto-scroll**: The current word auto-scrolls into view (center of screen)
- **CPU performance**: On slower CPUs, synthesis may take 5–10 seconds per sentence. Prefetching happens in a background thread.

## Notes

- **Kokoro models**: Available voices include US & UK English female/male, Brazilian Portuguese, Spanish, French, Hindi, Italian, Japanese, Mandarin.
- **Language codes**: `'a'` (US), `'b'` (UK), `'e'` (Spanish), `'f'` (French), `'h'` (Hindi), `'i'` (Italian), `'j'` (Japanese), `'p'` (Portuguese), `'z'` (Mandarin).
- **Memory**: The model + torch weights stay in RAM. On constrained systems, restart between long sessions.
- **Audio quality**: 24 kHz mono, 16-bit PCM WAV. Playback quality depends on your system audio.

## Troubleshooting

**`conda: command not found`** — Miniconda isn't installed yet, or the terminal was
opened before installing it. Install it from
<https://www.anaconda.com/download/success>, then close and reopen your terminal.

**`./run.sh: Permission denied`** — Run it as `bash run.sh` instead, or make it
executable once with `chmod +x run.sh`.

**Install fails mentioning Python 3.13 / "no matching distribution"** — Kokoro
requires Python 3.10–3.12. Make sure you created the environment with
`python=3.12` (Step 2) and that `conda activate speechifyPDF` is active.

**`Address already in use` / port 8000 busy** — Another program (or a previous run)
is using port 8000. Stop the old one, or start on a different port:
`uvicorn app:app --port 8001` and visit <http://127.0.0.1:8001>.

**"No extractable text found"** — The PDF is a scanned image (just pictures of
pages), so there's no real text to read. SpeechifyPDF reads text-based PDFs; it does
not do OCR. Try a PDF where you can select/copy the text.

**Nothing plays / no sound** — Check your system volume and that the browser tab
isn't muted. The first sentence also takes longer (one-time model download).

**Slow synthesis** — On a CPU, the first sentence can take 10–30s (model warm-up) and
later sentences a few seconds each. This is normal. Closing other heavy apps frees up
RAM/CPU and speeds it up.

**"espeak-ng library: ..."** — Informational: the bundled espeak-ng library is loaded
for grapheme-to-phoneme conversion. No action needed unless it reports a failure.

## License

This app wraps [Kokoro](https://github.com/hexgrad/kokoro) (Apache 2.0) and uses FastAPI and other open-source libraries. See their respective licenses.