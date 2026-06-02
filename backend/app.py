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
import hashlib
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
import httpx

import tts
from pdf_utils import extract_document

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

# Interpol cache: key -> (timestamp, result)
_interpol_cache: dict[str, tuple[float, dict]] = {}
_INTERPOL_CACHE_TTL = 300  # 5 minutes
_INTERPOL_BASE = "https://ws-public.interpol.int/notices/v1/red"


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


# =====================================================================
# INTERPOL RED NOTICES — live proxy search
# =====================================================================

class InterpolSearchRequest(BaseModel):
    name: str = Field(..., min_length=1, description="Surname")
    forename: Optional[str] = Field(None, description="First name")
    nationality: Optional[str] = Field(None, description="Two-letter country code")
    sexId: Optional[str] = Field(None, description="M, F, or U")
    ageMin: Optional[int] = Field(None, ge=0)
    ageMax: Optional[int] = Field(None, le=120)
    freeText: Optional[str] = Field(None, description="Free text search")
    page: int = Field(1, ge=1, description="Page number")
    resultPerPage: int = Field(20, ge=1, le=160)


def _interpol_cache_key(params: dict) -> str:
    raw = "|".join(f"{k}={v}" for k, v in sorted(params.items()) if v is not None)
    return hashlib.sha256(raw.encode()).hexdigest()


def _clean_interpol_cache():
    """Evict stale entries."""
    now = time.time()
    stale = [k for k, (ts, _) in _interpol_cache.items() if now - ts > _INTERPOL_CACHE_TTL]
    for k in stale:
        _interpol_cache.pop(k, None)


@app.post("/api/interpol/search")
async def interpol_search(req: InterpolSearchRequest):
    """Proxy search against the Interpol public Red Notices API.

    The browser cannot call Interpol directly (CORS / 403), so we relay
    the request server-side and normalise the response.
    """
    _clean_interpol_cache()

    # Build upstream query params
    params: dict[str, str | int] = {"name": req.name.strip()}
    if req.forename:
        params["forename"] = req.forename.strip()
    if req.nationality:
        params["nationality"] = req.nationality.strip().upper()
    if req.sexId:
        params["sexId"] = req.sexId.strip().upper()
    if req.ageMin is not None:
        params["ageMin"] = req.ageMin
    if req.ageMax is not None:
        params["ageMax"] = req.ageMax
    if req.freeText:
        params["freeText"] = req.freeText.strip()
    params["page"] = req.page
    params["resultPerPage"] = req.resultPerPage

    cache_key = _interpol_cache_key(params)
    cached = _interpol_cache.get(cache_key)
    if cached and (time.time() - cached[0]) < _INTERPOL_CACHE_TTL:
        return JSONResponse(cached[1])

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                _INTERPOL_BASE,
                params=params,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "SpeechifyPDF-SanctionsScreener/1.0",
                },
            )
        if resp.status_code != 200:
            raise HTTPException(resp.status_code, f"Interpol API returned {resp.status_code}")
        data = resp.json()
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Failed to reach Interpol API: {exc}")

    # Normalise the response for the frontend
    raw_notices = (data.get("_embedded") or {}).get("notices") or []
    notices = []
    for n in raw_notices:
        thumbnail = None
        imgs = (n.get("_links") or {}).get("images") or {}
        if isinstance(imgs, dict) and imgs.get("href"):
            thumbnail = imgs["href"]
        elif isinstance(imgs, list) and imgs:
            thumbnail = imgs[0].get("href")
        # Also try thumbnail link
        thumb_link = (n.get("_links") or {}).get("thumbnail") or {}
        if not thumbnail and isinstance(thumb_link, dict) and thumb_link.get("href"):
            thumbnail = thumb_link["href"]

        notices.append({
            "entity_id": n.get("entity_id", ""),
            "name": n.get("name", ""),
            "forename": n.get("forename", ""),
            "date_of_birth": n.get("date_of_birth", ""),
            "nationalities": n.get("nationalities") or [],
            "sex_id": n.get("sex_id", ""),
            "country_of_birth_id": n.get("country_of_birth_id", ""),
            "charge": n.get("arrest_warrants", [{}])[0].get("charge", "")
                      if n.get("arrest_warrants") else "",
            "issuing_country": n.get("arrest_warrants", [{}])[0].get("issuing_country_id", "")
                               if n.get("arrest_warrants") else "",
            "thumbnail": thumbnail,
        })

    result = {
        "total": data.get("total", 0),
        "page": req.page,
        "resultPerPage": req.resultPerPage,
        "notices": notices,
    }
    _interpol_cache[cache_key] = (time.time(), result)
    return JSONResponse(result)


# Serve the static frontend.
_static = Path(__file__).resolve().parent / "static"
if _static.is_dir():
    app.mount("/", StaticFiles(directory=str(_static), html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
