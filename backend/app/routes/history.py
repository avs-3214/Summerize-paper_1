"""
GET /history — returns the last 10 uploaded papers with cached summaries.
"""

from fastapi import APIRouter, HTTPException, Query, status
from app.models.schema import HistoryResponse

router = APIRouter()


@router.get(
    "/history",
    response_model=HistoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Get last 10 uploaded papers with cached summaries",
)
async def get_history(
    limit: int = Query(default=10, ge=1, le=20, description="Number of papers to return (max 20)"),
) -> HistoryResponse:
    try:
        from app.db.sqlite import get_recent_papers
        papers = get_recent_papers(limit=limit)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "internal_error", "detail": f"Could not fetch history: {exc}"},
        ) from exc
    return HistoryResponse(papers=papers)