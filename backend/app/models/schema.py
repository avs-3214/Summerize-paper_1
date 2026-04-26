"""
Pydantic v2 schemas — single source of truth for request/response shapes.
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
    paper_id:   str         = Field(..., json_schema_extra={"example": "3fa85f64-5717-4562-b3fc-2c963f66afa6"})
    title:      str         = Field(..., json_schema_extra={"example": "Attention Is All You Need"})
    num_chunks: int         = Field(..., ge=1, json_schema_extra={"example": 42})
    status:     PaperStatus = Field(default=PaperStatus.ready)


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

class ValidationRequest(BaseModel):
    """Request body for POST /validate."""
 
    paper_id: str = Field(
        ...,
        json_schema_extra={"example": "3fa85f64-5717-4562-b3fc-2c963f66afa6"},
    )
    tier: Tier = Field(
        ...,
        json_schema_extra={"example": "intermediate"},
    )
 
 
class ValidationResponse(BaseModel):
    """Response body for POST /validate."""
 
    paper_id:     str  = Field(..., json_schema_extra={"example": "3fa85f64-5717-4562-b3fc-2c963f66afa6"})
    tier:         Tier = Field(..., json_schema_extra={"example": "intermediate"})
 
    # ROUGE scores (F1)
    rouge1:  float = Field(..., json_schema_extra={"example": 0.4123})
    rouge2:  float = Field(..., json_schema_extra={"example": 0.1876})
    rougeL:  float = Field(..., json_schema_extra={"example": 0.3541})
 
    # BERTScore F1
    bertscore_f1: float = Field(..., json_schema_extra={"example": 0.8712})
 
    # Thresholds used for this tier
    thresholds: dict[str, float] = Field(
        ...,
        json_schema_extra={"example": {"rouge1": 0.35, "rouge2": 0.12, "rougeL": 0.28, "bertscore": 0.84}},
    )
 
    # Per-metric pass/fail
    metric_pass: dict[str, bool] = Field(
        ...,
        json_schema_extra={"example": {"rouge1": True, "rouge2": True, "rougeL": True, "bertscore": True}},
    )
 
    # Overall verdict
    overall_valid: bool = Field(..., json_schema_extra={"example": True})
    verdict:       str  = Field(..., json_schema_extra={"example": "✅ Summary is VALID for tier: INTERMEDIATE"})
 
    validated_at: datetime = Field(..., json_schema_extra={"example": "2024-01-15T10:30:00Z"})