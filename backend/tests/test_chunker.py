"""
Run: pytest tests/test_chunker.py -v
No fixtures needed.
"""

import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.chunker import (
    chunk_text, chunk_from_sections, get_chunk_texts,
    get_chunk_metadatas, TARGET_CHUNK_SIZE, MAX_CHUNK_SIZE,
)

SAMPLE_SECTIONS = [
    {"name": "abstract",      "text": "We present a novel approach to neural machine translation."},
    {"name": "introduction",  "text": "Background. " * 80},   # ~960 chars — forces chunking
    {"name": "results",       "text": "We achieve 28.4 BLEU on WMT 2014."},
]


# --- chunk_text (backward compat) ---

def test_chunk_text_empty():
    assert chunk_text("") == []

def test_chunk_text_short_returns_single():
    chunks = chunk_text("Short text.")
    assert len(chunks) == 1

def test_chunk_text_no_chunk_exceeds_max():
    long = "Word " * 500
    for chunk in chunk_text((long + "\n\n") * 3):
        assert len(chunk) <= MAX_CHUNK_SIZE, f"Chunk length {len(chunk)} exceeds MAX_CHUNK_SIZE {MAX_CHUNK_SIZE}"


# --- chunk_from_sections ---

def test_chunk_from_sections_returns_dicts():
    result = chunk_from_sections(SAMPLE_SECTIONS)
    assert isinstance(result, list)
    for item in result:
        assert "text" in item
        assert "section" in item
        assert "chunk_index" in item


def test_chunk_from_sections_section_tags_correct():
    result = chunk_from_sections(SAMPLE_SECTIONS)
    # abstract is short — should produce 1 chunk tagged "abstract"
    abstract_chunks = [c for c in result if c["section"] == "abstract"]
    assert len(abstract_chunks) >= 1
    assert abstract_chunks[0]["section"] == "abstract"


def test_chunk_from_sections_chunk_indices_are_global_and_unique():
    result = chunk_from_sections(SAMPLE_SECTIONS)
    indices = [c["chunk_index"] for c in result]
    assert indices == sorted(set(indices)), "chunk_index should be unique and sequential"


def test_chunk_from_sections_empty_sections():
    assert chunk_from_sections([]) == []


def test_chunk_from_sections_skips_empty_text():
    sections = [{"name": "abstract", "text": "   "}, {"name": "intro", "text": "Some text."}]
    result = chunk_from_sections(sections)
    assert all(c["text"].strip() for c in result)


# --- get_chunk_texts and get_chunk_metadatas ---

def test_get_chunk_texts_returns_strings():
    chunks = chunk_from_sections(SAMPLE_SECTIONS)
    texts = get_chunk_texts(chunks)
    assert all(isinstance(t, str) for t in texts)


def test_get_chunk_metadatas_has_paper_id():
    chunks = chunk_from_sections(SAMPLE_SECTIONS)
    metas = get_chunk_metadatas(chunks, "test-paper-id")
    assert all(m["paper_id"] == "test-paper-id" for m in metas)
    assert all("section" in m for m in metas)