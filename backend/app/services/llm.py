"""
Groq API client + tier-specific prompt templates.

Models:
  beginner:     llama-3.1-8b-instant    (128k context, 8k max output)
  intermediate: llama-3.3-70b-versatile (128k context, 32k max output)
  expert:       llama-3.3-70b-versatile (128k context, 32k max output)

Token budget reasoning:
  beginner:     400  out (~300 words)  — 250 word target, small buffer fine
  intermediate: 1500 out (~1100 words) — 5 sections × 3-4 sentences each needs
                                         room; 900 caused cut-off on last sections
  expert:       3500 out (~2600 words) — 7 technical sections + reduce step in
                                         map-reduce needs headroom; 2200 cut off
                                         Experimental Setup and Limitations consistently
  map step:     300  out per chunk     — 3-5 sentences, fits comfortably

Rate limit handling:
  Uses tenacity AsyncRetrying on 429s with exponential backoff (3 attempts).
  Raises HTTPException(429) with retry_after if all retries exhausted.
"""

from __future__ import annotations

import asyncio
import os

from fastapi import HTTPException, status
from groq import AsyncGroq, RateLimitError
from tenacity import (
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    AsyncRetrying,
)

# ---------------------------------------------------------------------------
# Async client (singleton)

_async_client: AsyncGroq | None = None


def _get_async_client() -> AsyncGroq:
    global _async_client
    if _async_client is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY not set in environment / .env")
        _async_client = AsyncGroq(api_key=api_key)
    return _async_client


# ---------------------------------------------------------------------------
# Model + token config

MODEL_BEGINNER = os.getenv("MODEL_BEGINNER", "llama-3.1-8b-instant")
MODEL_ADVANCED = os.getenv("MODEL_ADVANCED", "llama-3.3-70b-versatile")

TIER_MODEL = {
    "beginner":     MODEL_BEGINNER,
    "intermediate": MODEL_ADVANCED,
    "expert":       MODEL_ADVANCED,
}

TIER_MAX_TOKENS = {
    "beginner":     400,    # ~300 words out — 250 word target, fine
    "intermediate": 1500,   # ~1100 words out — 5 sections need room, was 900 (cut off)
    "expert":       3500,   # ~2600 words out — 7 sections + map-reduce reduce step
    "_map_step":    300,    # per-chunk mini summary in expert map phase
}

SYSTEM_PROMPT = (
    "You are an expert research assistant that summarizes academic papers. "
    "Always respond in clean Markdown. Be accurate — do not hallucinate claims "
    "that are not supported by the provided text. "
    "Follow the output format shown in the example exactly. "
    "Do not truncate your response — complete every section fully."
)


# ---------------------------------------------------------------------------
# Prompts — with few-shot examples

_BEGINNER_EXAMPLE = """\
Example of a good beginner summary (for a paper on neural translation):
---
Modern computers struggle to translate human languages because understanding \
a sentence requires connecting ideas that may be far apart — like knowing that \
"it" in the last sentence refers to something mentioned earlier.

This paper solves that by teaching the computer to pay "attention" — meaning \
it looks at every word in the sentence at once and decides which ones matter \
most for translating each new word. No more reading left-to-right one word at a time.

In tests on standard translation benchmarks, this approach beat every previous \
method while also training four times faster.

This matters because better translation systems help billions of people access \
information in their own language.
---"""

_INTERMEDIATE_EXAMPLE = """\
Example of a good intermediate summary (for a paper on neural translation):
---
## Overview
This paper introduces the Transformer, a sequence-to-sequence model that \
replaces recurrent layers entirely with self-attention, enabling parallelised \
training and better long-range dependency modelling.

## Key Contributions
- First architecture to rely solely on attention mechanisms (no RNN/CNN)
- Multi-head attention with h=8 parallel attention heads, each with d_k=64 dimensions
- Positional encodings allow the model to understand word order without recurrence
- Achieves 28.4 BLEU on WMT 2014 EN-DE, surpassing prior best by over 2 BLEU points

## Methodology
The encoder and decoder each consist of 6 stacked layers. Each layer contains \
a multi-head self-attention sub-layer followed by a position-wise feed-forward \
network (FFN) with hidden size 2048. Residual connections and layer normalisation \
wrap each sub-layer. For the decoder, a third sub-layer performs cross-attention \
over the encoder output.

## Results & Findings
The Transformer outperforms all prior models on EN-DE and EN-FR translation. \
On EN-FR, it achieves 41.0 BLEU, more than halving the training cost of the \
previous best. Training on 8 P100 GPUs took 3.5 days for the base model.

## Takeaway
Self-attention is a viable and superior replacement for recurrence in sequence \
modelling. The architecture's parallelism makes it far cheaper to train at scale, \
which is why it became the foundation for GPT, BERT, and all modern LLMs.
---"""


def _build_prompt(chunks: list[str], tier: str) -> str:
    context = "\n\n---\n\n".join(chunks)

    if tier == "beginner":
        return f"""{_BEGINNER_EXAMPLE}

Now write a beginner summary for the paper excerpts below. \
Follow the same 4-paragraph structure shown in the example above. \
Use plain English. No jargon — if a technical term is unavoidable, explain it \
in one sentence. Do NOT use bullet points. Aim for ~250 words.

Paper excerpts:
{context}

Write the beginner summary now:"""

    if tier == "intermediate":
        return f"""{_INTERMEDIATE_EXAMPLE}

Now write an intermediate summary for the paper excerpts below using those \
exact Markdown headings. Assume the reader has a university-level background \
but is not a specialist in this specific field. \
Be specific — include numbers, model names, dataset names, and metrics wherever \
they appear in the text. Each section should be 3-5 sentences or a bullet list \
with enough detail to be genuinely useful. Aim for 800-1000 words total.

Paper excerpts:
{context}

Write the intermediate summary now:"""

    if tier == "expert":
        return f"""Below are excerpts from a research paper. Write a comprehensive \
expert-level technical summary using these exact Markdown headings:

## Abstract & Motivation
## Prior Work & Gap
## Technical Approach
## Experimental Setup
## Results
## Limitations
## Future Work & Impact

Rules:
- Assume the reader is a domain expert. Use precise technical language.
- Preserve specific metrics, baselines, ablations, and statistical details \
  from the text. Include numbers wherever they appear.
- Critically evaluate claims where the evidence is weak or missing.
- Each section should be substantive — 3-6 sentences minimum.
- If a section has no information in the excerpts, write \
  "Not covered in retrieved excerpts."
- Complete all 7 sections fully. Do not truncate.
- Aim for 1200-1500 words total.

Paper excerpts:
{context}

Write the expert summary now:"""

    raise ValueError(f"Unknown tier: {tier}")


# ---------------------------------------------------------------------------
# Async Groq call with tenacity retry

async def _call_groq_async(model: str, prompt: str, max_tokens: int) -> str:
    """
    Async Groq call with exponential backoff retry on RateLimitError.
    3 attempts, waits 5→30s between retries.
    """
    client = _get_async_client()

    async for attempt in AsyncRetrying(
        retry=retry_if_exception_type(RateLimitError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=5, max=30),
        reraise=True,
    ):
        with attempt:
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": prompt},
                ],
                max_tokens=max_tokens,
                temperature=0.3,
            )
            return response.choices[0].message.content or ""

    return ""  # unreachable, satisfies type checker


# ---------------------------------------------------------------------------
# Expert map-reduce — fully concurrent

async def _expert_map_reduce(chunks: list[str]) -> str:
    """
    Map: summarize every chunk concurrently with asyncio.gather.
    Reduce: synthesize all mini-summaries into one expert summary.

    Sequential (v1): N chunks × ~5s each = N*5s
    Concurrent (v2): all map calls fire at once → ~5s map + ~15s reduce = ~20s total
    """
    async def _map_one(i: int, chunk: str) -> str:
        map_prompt = (
            f"Summarize the following section of a research paper in 3-5 technical sentences. "
            f"Preserve all specific numbers, method names, metrics, and baselines.\n\n"
            f"Section {i + 1}:\n{chunk}\n\nTechnical summary:"
        )
        result = await _call_groq_async(
            model=MODEL_ADVANCED,
            prompt=map_prompt,
            max_tokens=TIER_MAX_TOKENS["_map_step"],
        )
        return f"**Section {i + 1}:**\n{result}"

    # All map calls fire simultaneously
    mini_summaries: list[str] = await asyncio.gather(
        *[_map_one(i, chunk) for i, chunk in enumerate(chunks)]
    )

    # Reduce into full expert summary — uses the full 3500 token budget
    combined = "\n\n".join(mini_summaries)
    reduce_prompt = _build_prompt([combined], tier="expert")
    return await _call_groq_async(
        model=MODEL_ADVANCED,
        prompt=reduce_prompt,
        max_tokens=TIER_MAX_TOKENS["expert"],
    )


# ---------------------------------------------------------------------------
# Public entry point (async)

async def generate_summary(chunks: list[str], tier: str) -> str:
    """
    Generate a summary for the given chunks at the specified tier.

    Args:
        chunks: List of text chunks from retriever.py
        tier:   "beginner" | "intermediate" | "expert"

    Returns:
        Summary as a Markdown string.

    Raises:
        HTTPException(429) if Groq rate limit is hit after all retries.
        HTTPException(500) if any other Groq error occurs.
    """
    if not chunks:
        return (
            "_No content could be retrieved for this paper. "
            "Try re-uploading the PDF._"
        )

    model      = TIER_MODEL[tier]
    max_tokens = TIER_MAX_TOKENS[tier]

    try:
        if tier == "expert" and len(chunks) > 4:
            return await _expert_map_reduce(chunks)
        else:
            prompt = _build_prompt(chunks, tier)
            return await _call_groq_async(
                model=model, prompt=prompt, max_tokens=max_tokens
            )

    except RateLimitError:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error":       "rate_limited",
                "detail":      "Groq rate limit hit. Please wait and retry.",
                "retry_after": 30,
            },
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "llm_error", "detail": f"Groq call failed: {exc}"},
        ) from exc