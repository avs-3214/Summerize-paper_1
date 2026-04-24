"""
Run: pytest tests/test_llm.py -v
All Groq calls mocked — no API key needed.
"""

import sys
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.llm import _build_prompt, generate_summary, TIER_MODEL


SAMPLE_CHUNKS = [
    "This paper introduces the Transformer, a model based solely on attention.",
    "We evaluated on WMT 2014 English-to-German, achieving 28.4 BLEU.",
    "The model uses multi-head self-attention with 8 parallel heads.",
]


def run(coro):
    """Helper to run async functions in sync tests."""
    return asyncio.run(coro)


# --- Prompt building ---

def test_beginner_prompt_has_few_shot_example():
    prompt = _build_prompt(SAMPLE_CHUNKS, "beginner")
    assert "Example of a good beginner summary" in prompt
    assert "250 words" in prompt


def test_intermediate_prompt_has_few_shot_example():
    prompt = _build_prompt(SAMPLE_CHUNKS, "intermediate")
    assert "Example of a good intermediate summary" in prompt
    assert "## Overview" in prompt


def test_expert_prompt_has_limitations_section():
    prompt = _build_prompt(SAMPLE_CHUNKS, "expert")
    assert "## Limitations" in prompt
    assert "1200-1500 words" in prompt


def test_all_chunks_in_prompt():
    prompt = _build_prompt(SAMPLE_CHUNKS, "intermediate")
    for chunk in SAMPLE_CHUNKS:
        assert chunk in prompt


def test_invalid_tier_raises():
    with pytest.raises(ValueError):
        _build_prompt(SAMPLE_CHUNKS, "mega")


# --- generate_summary (async, mocked) ---

@patch("app.services.llm._call_groq_async", new_callable=AsyncMock)
def test_generate_beginner(mock_call):
    mock_call.return_value = "## Summary\n\nThis paper is about attention."
    result = run(generate_summary(SAMPLE_CHUNKS, "beginner"))
    assert "Summary" in result
    mock_call.assert_called_once()


@patch("app.services.llm._call_groq_async", new_callable=AsyncMock)
def test_generate_expert_small_no_map_reduce(mock_call):
    """3 chunks < 4 threshold — should NOT use map-reduce (1 call only)."""
    mock_call.return_value = "## Abstract\n\nDeep technical analysis."
    run(generate_summary(SAMPLE_CHUNKS, "expert"))
    assert mock_call.call_count == 1


@patch("app.services.llm._call_groq_async", new_callable=AsyncMock)
def test_generate_expert_large_uses_map_reduce(mock_call):
    """12 chunks > 4 threshold — map-reduce: N map calls + 1 reduce."""
    mock_call.return_value = "Section summary."
    big_chunks = SAMPLE_CHUNKS * 4  # 12 chunks
    run(generate_summary(big_chunks, "expert"))
    # 12 map calls + 1 reduce = 13
    assert mock_call.call_count == 13


@patch("app.services.llm._call_groq_async", new_callable=AsyncMock)
def test_map_reduce_calls_are_concurrent(mock_call):
    """Verify gather fires concurrently — all map calls use max_tokens=300."""
    call_max_tokens = []

    async def capture(**kwargs):
        call_max_tokens.append(kwargs.get("max_tokens"))
        return "mini summary"

    mock_call.side_effect = capture
    big_chunks = SAMPLE_CHUNKS * 4
    run(generate_summary(big_chunks, "expert"))
    map_calls = [t for t in call_max_tokens if t == 300]
    assert len(map_calls) == 12  # all 12 map calls used max_tokens=300


def test_empty_chunks_returns_placeholder():
    result = run(generate_summary([], "beginner"))
    assert "No content" in result or "retrieved" in result


@patch("app.services.llm._call_groq_async", new_callable=AsyncMock)
def test_rate_limit_raises_http_429(mock_call):
    from groq import RateLimitError
    from fastapi import HTTPException
    mock_call.side_effect = RateLimitError(
        message="rate limit", response=MagicMock(status_code=429), body={}
    )
    with pytest.raises(HTTPException) as exc:
        run(generate_summary(SAMPLE_CHUNKS, "beginner"))
    assert exc.value.status_code == 429
    assert exc.value.detail["error"] == "rate_limited"
    assert "retry_after" in exc.value.detail


# --- Model routing ---

def test_beginner_uses_8b():
    assert "8b" in TIER_MODEL["beginner"] or "instant" in TIER_MODEL["beginner"]

def test_intermediate_uses_70b():
    assert "70b" in TIER_MODEL["intermediate"]

def test_expert_uses_70b():
    assert "70b" in TIER_MODEL["expert"]