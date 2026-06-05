"""Kokoro TTS wrapper.

Synthesises a chunk of text into 24 kHz mono WAV audio and returns per-word
timings (start/end seconds) used by the frontend to highlight words in sync
with playback. Designed for CPU: a single shared pipeline, serialised behind a
lock, generating one sentence at a time.
"""
from __future__ import annotations

import io
import threading

# misaki's English G2P falls back to espeak-ng for out-of-vocabulary words.
# espeakng_loader ships the shared library so no system install is needed.
try:
    import espeakng_loader
    from phonemizer.backend.espeak.wrapper import EspeakWrapper

    EspeakWrapper.set_library(espeakng_loader.get_library_path())
    EspeakWrapper.set_data_path(espeakng_loader.get_data_path())
except Exception as exc:  # pragma: no cover - best effort
    print(f"[tts] espeak-ng loader unavailable: {exc}")

import numpy as np
import soundfile as sf

SAMPLE_RATE = 24000

# Map our short voice ids to Kokoro voices + language codes.
VOICES = {
    "af_heart": {"label": "Heart (US female)", "lang": "a"},
    "af_bella": {"label": "Bella (US female)", "lang": "a"},
    "am_michael": {"label": "Michael (US male)", "lang": "a"},
    "am_fenrir": {"label": "Fenrir (US male)", "lang": "a"},
    "bf_emma": {"label": "Emma (UK female)", "lang": "b"},
    "bm_george": {"label": "George (UK male)", "lang": "b"},
}
DEFAULT_VOICE = "af_heart"

_pipelines: dict[str, object] = {}
_lock = threading.Lock()


def _get_pipeline(lang_code: str):
    """Lazily build (and cache) a KPipeline per language code."""
    if lang_code not in _pipelines:
        from kokoro import KPipeline

        _pipelines[lang_code] = KPipeline(lang_code=lang_code)
    return _pipelines[lang_code]


def _group_words(tokens, time_offset: float) -> list[dict]:
    """Group Kokoro tokens into display words.

    A token whose `whitespace` is empty is glued to the following token (this is
    how trailing punctuation and quotes attach, e.g. 'dog' + '.' -> 'dog.'). We
    accumulate tokens until one carries trailing whitespace, then emit a word.
    """
    words: list[dict] = []
    group: list = []

    def flush():
        if not group:
            return
        text = "".join(t.text or "" for t in group)
        if not text:
            group.clear()
            return
        starts = [t.start_ts for t in group if getattr(t, "start_ts", None) is not None]
        ends = [t.end_ts for t in group if getattr(t, "end_ts", None) is not None]
        start = (min(starts) + time_offset) if starts else None
        end = (max(ends) + time_offset) if ends else None
        words.append({"text": text, "start": start, "end": end})
        group.clear()

    for t in tokens:
        group.append(t)
        if (getattr(t, "whitespace", "") or "") != "":
            flush()
    flush()
    return words


def _fill_missing_timings(words: list[dict], total: float) -> None:
    """Ensure every word has a usable [start, end] by filling gaps."""
    n = len(words)
    for i, w in enumerate(words):
        if w["start"] is None:
            prev_end = words[i - 1]["end"] if i > 0 and words[i - 1]["end"] is not None else 0.0
            w["start"] = prev_end
        if w["end"] is None:
            nxt = words[i + 1]["start"] if i + 1 < n and words[i + 1]["start"] is not None else total
            w["end"] = max(w["start"], nxt if nxt is not None else total)


def synthesize(text: str, voice: str = DEFAULT_VOICE, speed: float = 1.0) -> dict:
    """Synthesise `text`. Returns {duration, words:[{i,text,start,end}], wav: bytes}."""
    voice = voice if voice in VOICES else DEFAULT_VOICE
    lang = VOICES[voice]["lang"]
    speed = max(0.5, min(2.0, float(speed)))

    text = (text or "").strip()
    if not text:
        return {"duration": 0.0, "words": [], "wav": _wav_bytes(np.zeros(0, dtype=np.float32))}

    with _lock:
        pipeline = _get_pipeline(lang)
        audio_chunks: list[np.ndarray] = []
        words: list[dict] = []
        offset = 0.0  # seconds of audio already emitted (Kokoro may yield >1 chunk)

        for result in pipeline(text, voice=voice, speed=speed):
            audio = result.audio
            if audio is None:
                continue
            audio = audio.detach().cpu().numpy().astype(np.float32) if hasattr(audio, "detach") else np.asarray(audio, dtype=np.float32)
            if getattr(result, "tokens", None):
                words.extend(_group_words(result.tokens, offset))
            audio_chunks.append(audio)
            offset += len(audio) / SAMPLE_RATE

    full = np.concatenate(audio_chunks) if audio_chunks else np.zeros(0, dtype=np.float32)
    duration = len(full) / SAMPLE_RATE
    _fill_missing_timings(words, duration)
    for i, w in enumerate(words):
        w["i"] = i
    return {"duration": duration, "words": words, "wav": _wav_bytes(full)}


def _wav_bytes(samples: np.ndarray) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, samples, SAMPLE_RATE, format="WAV", subtype="PCM_16")
    return buf.getvalue()
