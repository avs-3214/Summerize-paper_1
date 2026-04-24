"""
PDF parsing using PyMuPDF4LLM.

Improvements over v1:
  - page_chunks=True: respects actual document structure instead of one big string
  - Section detection: identifies Abstract, Introduction, Methodology etc. from headings
  - Returns structured page list + detected sections so chunker can tag chunks correctly

Returns:
    {
        "title":    str,           # from PDF metadata or first heading
        "text":     str,           # full text joined (for backward compat)
        "pages":    int,           # page count
        "page_chunks": list[dict], # per-page dicts with text + page number
        "sections": list[dict],    # detected sections: [{name, start_char, text}]
    }
"""

from pathlib import Path
import re
import pymupdf4llm
import pymupdf


# Section headings commonly found in academic papers (order matters — checked top-down)
KNOWN_SECTIONS = [
    "abstract",
    "introduction",
    "related work",
    "background",
    "methodology",
    "method",
    "approach",
    "model",
    "architecture",
    "experiment",
    "experimental setup",
    "evaluation",
    "results",
    "discussion",
    "conclusion",
    "limitations",
    "future work",
    "references",
    "appendix",
]

# Regex: matches lines like "# Abstract", "## 2. Methodology", "RESULTS"
_SECTION_RE = re.compile(
    r"^(?:#{1,3}\s*)?(?:\d+[\.\d]*\s+)?("
    + "|".join(re.escape(s) for s in KNOWN_SECTIONS)
    + r")s?\b",
    re.IGNORECASE,
)


def parse_pdf(file_path: str) -> dict:
    """
    Parse a PDF file into structured page chunks with section tags.

    Args:
        file_path: Absolute or relative path to the PDF.

    Returns:
        dict with keys: title, text, pages, page_chunks, sections

    Raises:
        ValueError: if file doesn't exist or has no extractable text.
    """
    path = Path(file_path)
    if not path.exists():
        raise ValueError(f"File not found: {file_path}")

    # --- Extract per-page markdown chunks ---
    # page_chunks=True returns a list of dicts:
    # [{"text": str, "page": int, "images": [...], "metadata": {...}}, ...]
    raw_page_chunks: list[dict] = pymupdf4llm.to_markdown(
        str(path),
        page_chunks=True,
    )

    if not raw_page_chunks:
        raise ValueError(f"No text could be extracted from {path.name}")

    # Normalise: ensure every page has a "text" key and it's non-empty
    page_chunks = [
        {"text": p.get("text", "").strip(), "page": p.get("page", i)}
        for i, p in enumerate(raw_page_chunks)
        if p.get("text", "").strip()
    ]

    if not page_chunks:
        raise ValueError(f"No text could be extracted from {path.name}")

    # Full text for backward compatibility (used by chunker)
    full_text = "\n\n".join(p["text"] for p in page_chunks)

    # --- Page count ---
    doc = pymupdf.open(str(path))
    total_pages = doc.page_count
    doc.close()

    # --- Title ---
    title = _extract_title(str(path), full_text)

    # --- Section detection ---
    sections = _detect_sections(full_text)

    return {
        "title":       title,
        "text":        full_text,
        "pages":       total_pages,
        "page_chunks": page_chunks,
        "sections":    sections,
    }


# ---------------------------------------------------------------------------
# Helpers

def _extract_title(file_path: str, text: str) -> str:
    """Try PDF metadata first, fall back to first meaningful heading in text."""
    try:
        doc = pymupdf.open(file_path)
        meta_title = doc.metadata.get("title", "").strip()
        doc.close()
        if meta_title and len(meta_title) > 3:
            return meta_title
    except Exception:
        pass

    for line in text.splitlines():
        clean = line.strip().lstrip("#").strip()
        # Skip lines that look like section headers
        if clean and len(clean) > 3 and not _SECTION_RE.match(clean):
            return clean[:120]

    return "Untitled Paper"


def _detect_sections(text: str) -> list[dict]:
    """
    Scan full text for section headings and return a list of sections,
    each with their name and the text content that follows.

    Returns:
        [
            {"name": "abstract",     "start_char": 0,   "end_char": 450,  "text": "..."},
            {"name": "introduction", "start_char": 451, "end_char": 1200, "text": "..."},
            ...
        ]
    """
    lines = text.splitlines()
    hits: list[tuple[int, str, int]] = []  # (line_index, section_name, char_offset)

    char_offset = 0
    for i, line in enumerate(lines):
        m = _SECTION_RE.match(line.strip())
        if m:
            hits.append((i, m.group(1).lower(), char_offset))
        char_offset += len(line) + 1  # +1 for newline

    if not hits:
        # No sections detected — treat entire paper as one unnamed section
        return [{"name": "body", "start_char": 0, "end_char": len(text), "text": text}]

    sections: list[dict] = []
    for idx, (line_i, name, start_char) in enumerate(hits):
        end_char = hits[idx + 1][2] if idx + 1 < len(hits) else len(text)
        section_text = text[start_char:end_char].strip()
        sections.append({
            "name":       name,
            "start_char": start_char,
            "end_char":   end_char,
            "text":       section_text,
        })

    return sections