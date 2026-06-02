"""PDF text extraction and sentence/paragraph segmentation.

The reader displays a *reflowed* view: we pull the text out of the PDF, group it
into paragraphs and split each paragraph into sentences. Sentences are the unit
of TTS streaming, so we also cap their length to keep synthesis chunks small and
responsive on a CPU.

Paragraphs are reconstructed at the *line* level rather than trusting PyMuPDF's
"blocks", because many PDFs (especially printed web pages) emit one block per
wrapped line. We read every line with its position and font size, drop running
headers/footers and page numbers, then merge consecutive lines into a paragraph,
starting a new one on a large vertical gap, a font-size change (headings), or a
left-edge dedent (list items). Paragraphs that run off the bottom of a page are
stitched back to the top of the next.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from statistics import median

import fitz  # PyMuPDF

# Sentences longer than this are hard-wrapped at a word boundary so a single
# synthesis call never blocks playback for too long on a CPU.
MAX_SENTENCE_CHARS = 280

# --- Paragraph reconstruction tuning -------------------------------------
# A vertical gap larger than (line height x this) starts a new paragraph.
PARA_GAP_RATIO = 1.5
# Lines smaller than (body size x this) are treated as chrome and dropped.
CHROME_SIZE_RATIO = 0.75
# A heading is a line whose font is larger than (body size x this).
HEADING_SIZE_RATIO = 1.1
# A left edge this many points to the left of the previous line starts a new
# paragraph (e.g. the next item in a hanging-indent list).
DEDENT_TOL = 3.0
# Text repeated on at least this fraction of pages is a running header/footer.
REPEAT_PAGE_RATIO = 0.5
# A line is a sentence continuation across a page break if it does not end with
# terminal punctuation and the next line starts lower-case.
_TERMINAL_PUNCT = '.!?:;"”’)'
_PAGE_NUMBER = re.compile(r"^\s*\d+(\s*/\s*\d+)?\s*$")

# Collapse runs of whitespace but keep single spaces.
_WS = re.compile(r"\s+")
# Split after sentence-ending punctuation that is followed by whitespace.
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[]?[A-Z0-9])")

# Strip characters that render as invisible squares in the browser:
# - Private Use Area (U+E000–U+F8FF)
# - Supplementary Private Use Areas (U+F0000–U+10FFFF)
# - Replacement character (U+FFFD)
# - Geometric shapes (U+25A0–U+25FF) e.g. ■ ▢ ◆
# - Dingbats (U+2700–U+27BF) and misc symbols (U+2600–U+26FF)
# - Control characters except newline/tab/space
_JUNK_CHARS = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f"         # C0 controls
    r"\uE000-\uF8FF"                              # Private Use Area
    r"\uFFFD"                                     # Replacement char
    r"\u25A0-\u25FF"                              # Geometric shapes
    r"\u2600-\u26FF"                              # Misc symbols
    r"\u2700-\u27BF"                              # Dingbats
    r"\U000F0000-\U0010FFFF"                      # Supplementary PUA
    r"]+"
)

# Check if a cleaned string has any actual readable content.
_HAS_ALNUM = re.compile(r"[a-zA-Z0-9]")


@dataclass
class Document:
    title: str
    sentences: list[str] = field(default_factory=list)
    # paragraphs[i] is a list of indices into `sentences`, in reading order.
    paragraphs: list[list[int]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "sentences": self.sentences,
            "paragraphs": self.paragraphs,
        }


def _clean(text: str) -> str:
    # Strip junk/non-printable characters that render as squares.
    text = _JUNK_CHARS.sub("", text)
    # Join hyphenated line breaks ("exam-\nple" -> "example").
    text = re.sub(r"-\n(?=[a-z])", "", text)
    return _WS.sub(" ", text).strip()


def _hard_wrap(sentence: str) -> list[str]:
    """Split an over-long sentence into <= MAX_SENTENCE_CHARS chunks."""
    if len(sentence) <= MAX_SENTENCE_CHARS:
        return [sentence]
    chunks: list[str] = []
    words = sentence.split(" ")
    cur = ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > MAX_SENTENCE_CHARS:
            chunks.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}" if cur else w
    if cur:
        chunks.append(cur)
    return chunks


def _split_sentences(paragraph: str) -> list[str]:
    paragraph = _clean(paragraph)
    if not paragraph or not _HAS_ALNUM.search(paragraph):
        return []
    out: list[str] = []
    for part in _SENT_SPLIT.split(paragraph):
        part = part.strip()
        if part:
            out.extend(_hard_wrap(part))
    return out


@dataclass
class _Line:
    text: str
    size: float  # largest span font size on the line
    x0: float    # left edge
    y0: float    # top edge
    page: int


def _page_lines(page, page_index: int) -> list[_Line]:
    """Return the text lines on a page, in natural reading order."""
    data = page.get_text("dict")
    lines: list[_Line] = []
    for block in data.get("blocks", []):
        if block.get("type", 0) != 0:  # 0 = text, 1 = image
            continue
        for ln in block.get("lines", []):
            spans = ln.get("spans", [])
            text = "".join(s.get("text", "") for s in spans)
            if not text.strip():
                continue
            size = max((s.get("size", 0.0) for s in spans), default=0.0)
            x0, y0 = ln["bbox"][0], ln["bbox"][1]
            lines.append(_Line(text, size, x0, y0, page_index))
    # Sort top-to-bottom, then left-to-right, for single-column reading order.
    lines.sort(key=lambda l: (round(l.y0, 1), round(l.x0, 1)))
    return lines


def _is_chrome(text: str, size: float, body_size: float, repeated: set[str]) -> bool:
    """True for running headers/footers, page numbers and sub-body chrome."""
    if size and size < body_size * CHROME_SIZE_RATIO:
        return True
    if _PAGE_NUMBER.match(text):
        return True
    if text.strip().lower() in repeated:
        return True
    return False


def _join_lines(parts: list[str]) -> str:
    """Join wrapped lines into one string, healing end-of-line hyphenation."""
    out = ""
    for raw in parts:
        t = raw.strip()
        if not t:
            continue
        if not out:
            out = t
        elif len(out) > 1 and out[-1] == "-" and out[-2].isalpha():
            out = out[:-1] + t  # "exam-" + "ple" -> "example"
        else:
            out = f"{out} {t}"
    return out


def _starts_break(line: _Line, prev: _Line, line_height: float, body_size: float) -> bool:
    """Whether `line` begins a new paragraph relative to `prev` (same page)."""
    gap = line.y0 - prev.y0
    if gap > line_height * PARA_GAP_RATIO:
        return True
    # A change in font size means a heading boundary (either direction).
    if abs(line.size - prev.size) > 0.5:
        return True
    # A dedent (back toward the margin) starts the next list item / block.
    if line.x0 < prev.x0 - DEDENT_TOL:
        return True
    return False


def _collect_paragraphs(doc) -> list[str]:
    """Reconstruct reading-order paragraphs from the PDF's lines."""
    pages = [_page_lines(page, i) for i, page in enumerate(doc)]
    all_lines = [ln for page in pages for ln in page]
    if not all_lines:
        return []

    body_size = median(ln.size for ln in all_lines) or 0.0

    # Identify running headers/footers: short lines repeated across many pages.
    counts: Counter[str] = Counter()
    for page in pages:
        for norm in {ln.text.strip().lower() for ln in page}:
            counts[norm] += 1
    threshold = max(2, int(len(pages) * REPEAT_PAGE_RATIO))
    repeated = {t for t, c in counts.items() if c >= threshold and len(t) < 80}

    # Typical line height = median vertical gap between adjacent lines on a page.
    gaps = [
        b.y0 - a.y0
        for page in pages
        for a, b in zip(page, page[1:])
        if 0 < b.y0 - a.y0 < 60
    ]
    line_height = median(gaps) if gaps else body_size * 1.4

    paragraphs: list[list[_Line]] = []
    prev: _Line | None = None
    for page in pages:
        kept = [
            ln for ln in page
            if not _is_chrome(ln.text, ln.size, body_size, repeated)
        ]
        for ln in kept:
            new_para = prev is None
            if not new_para and ln.page != prev.page:
                # Page boundary: continue the paragraph only if the previous line
                # ended mid-sentence and this one resumes in lower case.
                resumes = (
                    prev.text.strip()[-1:] not in _TERMINAL_PUNCT
                    and ln.text.strip()[:1].islower()
                )
                new_para = not resumes
            elif not new_para:
                new_para = _starts_break(ln, prev, line_height, body_size)
            if new_para:
                paragraphs.append([ln])
            else:
                paragraphs[-1].append(ln)
            prev = ln

    return [_join_lines([ln.text for ln in para]) for para in paragraphs]


def extract_document(pdf_bytes: bytes, filename: str = "document.pdf") -> Document:
    """Extract a reflowed Document from raw PDF bytes."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        meta_title = (doc.metadata or {}).get("title") or ""
        sentences: list[str] = []
        paragraphs: list[list[int]] = []

        for para_text in _collect_paragraphs(doc):
            para_sentences = _split_sentences(para_text)
            if not para_sentences:
                continue
            start = len(sentences)
            sentences.extend(para_sentences)
            paragraphs.append(list(range(start, len(sentences))))
    finally:
        doc.close()

    title = meta_title.strip() or _derive_title(filename)
    return Document(title=title, sentences=sentences, paragraphs=paragraphs)


def _derive_title(filename: str) -> str:
    name = re.sub(r"\.pdf$", "", filename, flags=re.IGNORECASE)
    name = name.replace("_", " ").replace("-", " ").strip()
    return name or "Document"
