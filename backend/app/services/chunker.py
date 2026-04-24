"""
Splits extracted text into overlapping, section-tagged chunks for embedding.
"""

from __future__ import annotations
import re

TARGET_CHUNK_SIZE = 800
MAX_CHUNK_SIZE    = 1200
OVERLAP_CHARS     = 150


def chunk_from_sections(sections: list[dict]) -> list[dict]:
    result: list[dict] = []
    global_index = 0
    for section in sections:
        section_name = section.get("name", "body")
        section_text = section.get("text", "")
        if not section_text.strip():
            continue
        for chunk in _split_into_chunks(section_text):
            result.append({
                "text":        chunk,
                "section":     section_name,
                "chunk_index": global_index,
            })
            global_index += 1
    return result


def get_chunk_texts(chunked: list[dict]) -> list[str]:
    return [c["text"] for c in chunked]


def get_chunk_metadatas(chunked: list[dict], paper_id: str) -> list[dict]:
    return [
        {
            "paper_id":    paper_id,
            "section":     c["section"],
            "chunk_index": c["chunk_index"],
        }
        for c in chunked
    ]


def chunk_text(text: str) -> list[str]:
    """Backward-compat: chunk plain text with no section metadata."""
    if not text or not text.strip():
        return []
    return _split_into_chunks(text)


def _split_into_chunks(text: str) -> list[str]:
    raw_paragraphs = re.split(r"\n{2,}", text)
    paragraphs = [p.strip() for p in raw_paragraphs if p.strip()]

    # Break oversized paragraphs at sentence boundaries (or hard-split)
    split_paragraphs: list[str] = []
    for para in paragraphs:
        if len(para) <= MAX_CHUNK_SIZE:
            split_paragraphs.append(para)
        else:
            split_paragraphs.extend(_split_on_sentences(para))

    chunks: list[str] = []
    current = ""

    for para in split_paragraphs:
        if not current:
            current = para
        elif len(current) + len(para) + 2 <= TARGET_CHUNK_SIZE:
            current += "\n\n" + para
        else:
            chunks.append(current)
            # Build overlap prefix — must not make the new chunk exceed MAX_CHUNK_SIZE
            raw_overlap = current[-OVERLAP_CHARS:] if len(current) > OVERLAP_CHARS else current
            candidate = raw_overlap + "\n\n" + para
            if len(candidate) <= MAX_CHUNK_SIZE:
                current = candidate
            else:
                # Overlap would push us over — start fresh without it
                current = para

    if current:
        chunks.append(current)

    return [c.strip() for c in chunks if c.strip()]


def _split_on_sentences(text: str) -> list[str]:
    """
    Split on sentence boundaries (.!?).
    If a single sentence still exceeds MAX_CHUNK_SIZE (e.g. no punctuation),
    hard-split at MAX_CHUNK_SIZE boundaries.
    """
    sentences = re.split(r"(?<=[.!?])\s+", text)
    parts: list[str] = []
    current = ""

    for sentence in sentences:
        # Sentence itself exceeds the limit — hard-split it immediately
        if len(sentence) > MAX_CHUNK_SIZE:
            if current:
                parts.append(current)
                current = ""
            for i in range(0, len(sentence), MAX_CHUNK_SIZE):
                parts.append(sentence[i:i + MAX_CHUNK_SIZE])
            continue

        if len(current) + len(sentence) + 1 <= MAX_CHUNK_SIZE:
            current = (current + " " + sentence).strip()
        else:
            if current:
                parts.append(current)
            current = sentence

    if current:
        parts.append(current)

    # Last resort: text had no punctuation at all — hard-split the whole thing
    if not parts:
        return [text[i:i + MAX_CHUNK_SIZE] for i in range(0, len(text), MAX_CHUNK_SIZE)]

    return parts