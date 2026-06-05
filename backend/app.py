"""FastAPI backend for the Kokoro PDF reader.

Endpoints:
  POST /api/upload            -> upload a PDF, get reflowed document structure
  GET  /api/voices            -> available voices
  GET  /api/tts/{doc}/{sid}   -> synth one sentence: audio (base64 wav) + word timings

Everything runs in-process and in-memory; this is a single-user local app.
Synthesis is CPU-bound and serialised in tts.synthesize, so we offload it to a
thread to keep the event loop responsive and cache results per (sentence,voice,speed).
"""
from __future__ import annotations

import base64
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

import tts
from pdf_utils import extract_document
from pydantic import BaseModel
import text_utils

class TextRequest(BaseModel):
    text: str | None = None
    title: str = "Pasted Text"
    url: str | None = None

app = FastAPI(title="SpeechifyPDF")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory stores. documents[doc_id] = Document; audio cache keyed by content.
_documents: dict[str, object] = {}
_audio_cache: dict[tuple, dict] = {}
MAX_DOCUMENTS = 16

@app.get("/api/voices")
def list_voices():
    return {
        "default": tts.DEFAULT_VOICE,
        "voices": [{"id": vid, "label": v["label"]} for vid, v in tts.VOICES.items()],
    }


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "Please upload a .pdf file.")
    data = await file.read()
    if not data:
        raise HTTPException(400, "The uploaded file is empty.")
    try:
        document = await run_in_threadpool(extract_document, data, file.filename)
    except Exception as exc:
        raise HTTPException(400, f"Could not read PDF: {exc}")

    if not document.sentences:
        raise HTTPException(422, "No extractable text found (the PDF may be scanned images).")

    # Evict oldest document if we exceed the cap (keeps memory bounded).
    if len(_documents) >= MAX_DOCUMENTS:
        oldest = next(iter(_documents))
        _documents.pop(oldest, None)
        for key in [k for k in _audio_cache if k[0] == oldest]:
            _audio_cache.pop(key, None)

    doc_id = uuid.uuid4().hex[:12]
    _documents[doc_id] = document
    payload = document.to_dict()
    payload["doc_id"] = doc_id
    payload["sentence_count"] = len(document.sentences)
    return payload

@app.post("/api/text")
async def upload_text(req: TextRequest):
    if req.url:
        try:
            text, title = await run_in_threadpool(text_utils.fetch_url_text, req.url)
            document = text_utils.create_document_from_text(text, title)
        except Exception as exc:
            raise HTTPException(400, f"Could not fetch URL: {exc}")
    else:
        if not req.text or not req.text.strip():
            raise HTTPException(400, "Text is empty.")
        document = text_utils.create_document_from_text(req.text, req.title)

    if not document.sentences:
        raise HTTPException(422, "No extractable text found.")

    if len(_documents) >= MAX_DOCUMENTS:
        oldest = next(iter(_documents))
        _documents.pop(oldest, None)
        for key in [k for k in _audio_cache if k[0] == oldest]:
            _audio_cache.pop(key, None)

    doc_id = uuid.uuid4().hex[:12]
    _documents[doc_id] = document
    payload = document.to_dict()
    payload["doc_id"] = doc_id
    payload["sentence_count"] = len(document.sentences)
    return payload


@app.get("/api/tts/{doc_id}/{sentence_id}")
async def tts_sentence(
    doc_id: str,
    sentence_id: int,
    voice: str = Query(tts.DEFAULT_VOICE),
    speed: float = Query(1.0, ge=0.5, le=2.0),
):
    document = _documents.get(doc_id)
    if document is None:
        raise HTTPException(404, "Unknown document id (re-upload the PDF).")
    if not (0 <= sentence_id < len(document.sentences)):
        raise HTTPException(404, "Sentence index out of range.")

    cache_key = (doc_id, sentence_id, voice, round(float(speed), 3))
    cached = _audio_cache.get(cache_key)
    if cached is None:
        text = document.sentences[sentence_id]
        result = await run_in_threadpool(tts.synthesize, text, voice, speed)
        audio_b64 = base64.b64encode(result["wav"]).decode("ascii")
        cached = {
            "sentence_id": sentence_id,
            "duration": result["duration"],
            "words": result["words"],
            "audio": f"data:audio/wav;base64,{audio_b64}",
        }
        _audio_cache[cache_key] = cached
    return JSONResponse(cached)


# Serve the static frontend.
_static = Path(__file__).resolve().parent / "static"
if _static.is_dir():
    app.mount("/", StaticFiles(directory=str(_static), html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
