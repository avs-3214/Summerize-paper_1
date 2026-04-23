"""
Pydantic v2 schemas — single source of truth for request/response shapes.
These mirror API_CONTRACTS.md exactly. If one changes, update both.
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, UUID4

# Enums

class Tier(str, Enum):
    """
    The three summary tiers. str mixin means Tier.beginner == "beginner" is True,
    which keeps FastAPI path/query param coercion working cleanly.
    """
    beginner = "beginner"
    intermediate = "intermediate"
    expert = "expert"


class PaperStatus(str, Enum):
    ready = "ready"
    processing = "processing"
    failed = "failed"

# /upload

class UploadResponse(BaseModel):
    """
    POST /upload → 200
    Returned after PDF is fully parsed, chunked, and embedded.
    """
    paper_id: str = Field(
        ...,
        description="UUID v4 identifying this paper. Use in all subsequent requests.",
        example="3fa85f64-5717-4562-b3fc-2c963f66afa6",
    )
    title: str = Field(
        ...,
        description="Extracted from PDF metadata or first heading found in the text.",
        example="Attention Is All You Need",
    )
    num_chunks: int = Field(
        ...,
        description="Number of text chunks stored in ChromaDB.",
        ge=1,
        example=42,
    )
    status: PaperStatus = Field(
        default=PaperStatus.ready,
        description="Always 'ready' on a 200 response.",
    )

# /summarize

class SummarizeRequest(BaseModel):
    """
    POST /summarize — request body
    """
    paper_id: str = Field(
        ...,
        description="UUID returned from /upload.",
        example="3fa85f64-5717-4562-b3fc-2c963f66afa6",
    )
    tier: Tier = Field(
        ...,
        description="Summary depth: beginner | intermediate | expert",
        example=Tier.intermediate,
    )


class SummarizeResponse(BaseModel):
    """
    POST /summarize → 200
    GET  /summarize/{paper_id}?tier=... → 200
    """
    paper_id: str = Field(
        ...,
        description="Echoes back the requested paper_id.",
        example="3fa85f64-5717-4562-b3fc-2c963f66afa6",
    )
    tier: Tier = Field(
        ...,
        description="Echoes back the requested tier.",
        example=Tier.intermediate,
    )
    summary_markdown: str = Field(
        ...,
        description=(
            "Full summary as a Markdown string. "
            "Render with react-markdown + remark-gfm on the frontend."
        ),
        example="## Summary\n\nThis paper introduces the Transformer architecture...",
    )
    from_cache: bool = Field(
        ...,
        description=(
            "True if result was served from SQLite cache and Groq was NOT called. "
            "GET /summarize always returns from_cache=True."
        ),
        example=False,
    )
    created_at: datetime = Field(
        ...,
        description="ISO 8601 UTC timestamp of when this summary was first generated.",
        example="2024-01-15T10:30:00Z",
    )

# Error shapes

class ErrorResponse(BaseModel):
    """
    Standard error envelope returned for all 4xx / 5xx responses.
    The frontend should check response.data.error for programmatic handling
    and response.data.detail for a human-readable message.
    """
    error: str = Field(
        ...,
        description="Machine-readable error slug.",
        example="paper_not_found",
    )
    detail: str = Field(
        ...,
        description="Human-readable message for display or logging.",
        example="No paper found with id 3fa85f64-5717-4562-b3fc-2c963f66afa6",
    )


class RateLimitErrorResponse(ErrorResponse):
    """
    429 rate limit response — includes retry_after so the frontend can
    display a countdown or auto-retry.
    """
    error: str = Field(default="rate_limited")
    retry_after: int = Field(
        ...,
        description="Seconds to wait before retrying.",
        ge=1,
        example=30,
    )