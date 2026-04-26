"""
Pydantic v2 schemas — single source of truth for request/response shapes.

Changes from v2:
  - UploadResponse: added optional `warning` and `sections_found` fields
    so callers (and frontends) can surface section-detection failures to users
"""

from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field


class Tier(str, Enum):
    beginner     = "beginner"
    intermediate = "intermediate"
    expert       = "expert"


class PaperStatus(str, Enum):
    ready      = "ready"
    processing = "processing"
    failed     = "failed"


class UploadResponse(BaseModel):
    paper_id:       str              = Field(..., json_schema_extra={"example": "3fa85f64-5717-4562-b3fc-2c963f66afa6"})
    title:          str              = Field(..., json_schema_extra={"example": "Attention Is All You Need"})
    num_chunks:     int              = Field(..., ge=1, json_schema_extra={"example": 42})
    status:         PaperStatus      = Field(default=PaperStatus.ready)
    # Optional — present when section detection partially or fully failed.
    # Frontend should show a yellow warning banner when `warning` is not None.
    warning:        str | None       = Field(default=None, json_schema_extra={"example": None})
    sections_found: list[str] | None = Field(default=None, json_schema_extra={"example": ["abstract", "introduction", "results"]})


class SummarizeRequest(BaseModel):
    paper_id: str  = Field(..., json_schema_extra={"example": "3fa85f64-5717-4562-b3fc-2c963f66afa6"})
    tier:     Tier = Field(..., json_schema_extra={"example": "intermediate"})


class SummarizeResponse(BaseModel):
    paper_id:         str      = Field(..., json_schema_extra={"example": "3fa85f64-5717-4562-b3fc-2c963f66afa6"})
    tier:             Tier     = Field(..., json_schema_extra={"example": "intermediate"})
    summary_markdown: str      = Field(..., json_schema_extra={"example": "## Summary\n\nThis paper introduces..."})
    from_cache:       bool     = Field(..., json_schema_extra={"example": False})
    created_at:       datetime = Field(..., json_schema_extra={"example": "2024-01-15T10:30:00Z"})


class ErrorResponse(BaseModel):
    error:  str = Field(..., json_schema_extra={"example": "paper_not_found"})
    detail: str = Field(..., json_schema_extra={"example": "No paper found with id ..."})


class RateLimitErrorResponse(ErrorResponse):
    error:       str = Field(default="rate_limited")
    retry_after: int = Field(..., ge=1, json_schema_extra={"example": 30})


# ---------------------------------------------------------------------------
# Query

class QueryRequest(BaseModel):
    paper_id: str  = Field(..., json_schema_extra={"example": "3fa85f64-5717-4562-b3fc-2c963f66afa6"})
    question: str  = Field(..., min_length=3, max_length=500, json_schema_extra={"example": "What dataset was used for training?"})
    tier:     Tier = Field(default=Tier.intermediate, json_schema_extra={"example": "intermediate"})


class QueryResponse(BaseModel):
    paper_id:        str      = Field(..., json_schema_extra={"example": "3fa85f64-5717-4562-b3fc-2c963f66afa6"})
    question:        str      = Field(..., json_schema_extra={"example": "What dataset was used for training?"})
    tier:            Tier     = Field(..., json_schema_extra={"example": "intermediate"})
    answer_markdown: str      = Field(..., json_schema_extra={"example": "The paper used the WMT 2014 dataset..."})
    from_cache:      bool     = Field(..., json_schema_extra={"example": False})
    created_at:      datetime = Field(..., json_schema_extra={"example": "2026-04-24T07:05:40Z"})


# ---------------------------------------------------------------------------
# History

class PaperSummaries(BaseModel):
    beginner:     str | None = None
    intermediate: str | None = None
    expert:       str | None = None


class PaperHistoryItem(BaseModel):
    paper_id:    str            = Field(..., json_schema_extra={"example": "3fa85f64-5717-4562-b3fc-2c963f66afa6"})
    title:       str            = Field(..., json_schema_extra={"example": "Attention Is All You Need"})
    num_chunks:  int            = Field(..., json_schema_extra={"example": 72})
    uploaded_at: datetime       = Field(..., json_schema_extra={"example": "2026-04-24T07:05:40Z"})
    summaries:   PaperSummaries = Field(default_factory=PaperSummaries)


class HistoryResponse(BaseModel):
    papers: list[PaperHistoryItem] = Field(default_factory=list)