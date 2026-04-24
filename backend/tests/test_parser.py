"""
Run: pytest tests/test_parser.py -v

Integration tests need tests/fixtures/sample.pdf:
    curl -L "https://arxiv.org/pdf/1706.03762" -o tests/fixtures/sample.pdf
"""

import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.parser import parse_pdf, _extract_title, _detect_sections, KNOWN_SECTIONS

FIXTURE_PDF = Path(__file__).parent / "fixtures" / "sample.pdf"


def has_fixture():
    return FIXTURE_PDF.exists()


# --- Unit tests (no fixture) ---

def test_parse_missing_file_raises():
    with pytest.raises(ValueError, match="File not found"):
        parse_pdf("/tmp/does_not_exist_abc123.pdf")


def test_extract_title_from_text():
    fake_text = "# Attention Is All You Need\n\nSome content."
    title = _extract_title("/tmp/fake.pdf", fake_text)
    assert "Attention Is All You Need" in title


def test_detect_sections_finds_known_headers():
    text = (
        "# Abstract\nWe present a model.\n\n"
        "# Introduction\nBackground here.\n\n"
        "# Conclusion\nWe conclude.\n"
    )
    sections = _detect_sections(text)
    names = [s["name"] for s in sections]
    assert "abstract" in names
    assert "introduction" in names
    assert "conclusion" in names


def test_detect_sections_returns_body_fallback():
    text = "Just some plain text with no headings at all."
    sections = _detect_sections(text)
    assert len(sections) == 1
    assert sections[0]["name"] == "body"


def test_detect_sections_text_content_non_empty():
    text = "## Abstract\nThis is the abstract.\n\n## Introduction\nThis is the intro."
    sections = _detect_sections(text)
    for s in sections:
        assert s["text"].strip()


def test_detect_sections_start_end_chars_ordered():
    text = "# Abstract\nText.\n\n# Introduction\nMore text."
    sections = _detect_sections(text)
    for i in range(len(sections) - 1):
        assert sections[i]["end_char"] == sections[i + 1]["start_char"]


# --- Integration tests (need fixture PDF) ---

@pytest.mark.skipif(not has_fixture(), reason="No fixture PDF")
def test_parse_returns_all_keys():
    result = parse_pdf(str(FIXTURE_PDF))
    for key in ("title", "text", "pages", "page_chunks", "sections"):
        assert key in result, f"Missing key: {key}"


@pytest.mark.skipif(not has_fixture(), reason="No fixture PDF")
def test_parse_page_chunks_are_dicts():
    result = parse_pdf(str(FIXTURE_PDF))
    assert isinstance(result["page_chunks"], list)
    assert all("text" in p and "page" in p for p in result["page_chunks"])


@pytest.mark.skipif(not has_fixture(), reason="No fixture PDF")
def test_parse_sections_have_required_keys():
    result = parse_pdf(str(FIXTURE_PDF))
    for s in result["sections"]:
        assert "name" in s and "text" in s and "start_char" in s


@pytest.mark.skipif(not has_fixture(), reason="No fixture PDF")
def test_parse_full_text_non_empty():
    result = parse_pdf(str(FIXTURE_PDF))
    assert len(result["text"].strip()) > 200


@pytest.mark.skipif(not has_fixture(), reason="No fixture PDF")
def test_parse_detects_at_least_one_known_section():
    result = parse_pdf(str(FIXTURE_PDF))
    names = {s["name"] for s in result["sections"]}
    assert names & set(KNOWN_SECTIONS), f"No known sections found, got: {names}"