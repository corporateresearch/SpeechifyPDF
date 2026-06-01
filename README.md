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

## Quick Start

### Requirements

- Python 3.12+
- ~8 GB RAM (torch + model)
- Ubuntu/Debian, macOS, or Windows

### Setup

```bash
cd SpeechifyPDF
conda create -n speechifyPDF python=3.12 -y
conda activate speechifyPDF
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r backend/requirements.txt
```

### Run

**On Linux/macOS:**
```bash
./run.sh
# Opens on http://127.0.0.1:8000
```

**On Windows:**
```bat
run.bat
:: Opens on http://127.0.0.1:8000
```

**Or run directly:**
```bash
conda activate speechifyPDF
cd backend
uvicorn app:app --host 127.0.0.1 --port 8000
# Visit http://127.0.0.1:8000
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

**"espeak-ng library: ..."** - The bundled espeak-ng library is loaded for grapheme-to-phoneme conversion. If misaki G2P fails, check Python environment.

**Slow synthesis** - Kokoro on CPU can take 5–10s per sentence. This is normal for a 24000 Hz inference. Close other apps to free RAM/CPU.

## License

This app wraps [Kokoro](https://github.com/hexgrad/kokoro) (Apache 2.0) and uses FastAPI and other open-source libraries. See their respective licenses.
