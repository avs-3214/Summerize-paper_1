"""
POST /summarize       — generate (or serve from cache) a tiered summary
GET  /summarize/{id}  — retrieve a cached summary only (never calls Groq)

Changes from v1:
  - generate_summary is now async — awaited here instead of called directly
"""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, status

from app.models.schema import SummarizeRequest, SummarizeResponse, Tier

router = APIRouter()


@router.post(
    "/summarize",
    response_model=SummarizeResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate or retrieve a tiered summary",
    description=(
        "Checks SQLite cache first. If a summary already exists for this "
        "paper+tier combination, returns it immediately (from_cache=true) "
        "without calling Groq. Otherwise retrieves relevant chunks from "
        "ChromaDB, reranks them, and calls Groq to generate a new summary."
    ),
    responses={
        404: {"description": "paper_id not found"},
        422: {"description": "Invalid tier"},
        429: {"description": "Groq rate limit hit — includes retry_after"},
        500: {"description": "LLM error or internal server error"},
    },
)
async def create_summary(body: SummarizeRequest) -> SummarizeResponse:
    try:
        from app.db.sqlite import get_paper, get_cached_summary, cache_summary
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "internal_error", "detail": "DB layer not yet initialised."},
        ) from exc

    # 1. Paper exists?
    paper = get_paper(body.paper_id)
    if paper is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "paper_not_found", "detail": f"No paper found with id {body.paper_id}"},
        )

    # 2. Cache hit?
    cached = get_cached_summary(paper_id=body.paper_id, tier=body.tier.value)
    if cached:
        return SummarizeResponse(
            paper_id=body.paper_id,
            tier=body.tier,
            summary_markdown=cached["summary_markdown"],
            from_cache=True,
            created_at=cached["created_at"],
        )

    # 3. Retrieve + generate (both async)
    try:
        from app.services.retriever import retrieve_chunks
        from app.services.llm import generate_summary

        chunks = retrieve_chunks(paper_id=body.paper_id, tier=body.tier.value)
        summary_markdown = await generate_summary(chunks=chunks, tier=body.tier.value)

    except NotImplementedError:
        summary_markdown = (
            f"## [{body.tier.value.capitalize()} Summary — stub]\n\n"
            "P2 and P3 have not yet implemented the retriever and LLM service.\n\n"
            "- **Tier:** " + body.tier.value + "\n"
            "- **Paper ID:** " + body.paper_id
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "llm_error", "detail": f"Summary generation failed: {exc}"},
        ) from exc

    # 4. Cache result (best-effort)
    now = datetime.now(timezone.utc)
    try:
        cache_summary(
            paper_id=body.paper_id,
            tier=body.tier.value,
            summary_markdown=summary_markdown,
            created_at=now,
        )
    except Exception:
        pass

    return SummarizeResponse(
        paper_id=body.paper_id,
        tier=body.tier,
        summary_markdown=summary_markdown,
        from_cache=False,
        created_at=now,
    )


@router.get(
    "/summarize/{paper_id}",
    response_model=SummarizeResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve a cached summary (never calls Groq)",
    responses={
        404: {"description": "Paper not found or no cached summary for this tier"},
        422: {"description": "Invalid tier query param"},
    },
)
async def get_summary(
    paper_id: str,
    tier: Tier = Query(..., description="beginner | intermediate | expert"),
) -> SummarizeResponse:
    try:
        from app.db.sqlite import get_paper, get_cached_summary
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "internal_error", "detail": "DB layer not yet initialised."},
        ) from exc

    paper = get_paper(paper_id)
    if paper is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "paper_not_found", "detail": f"No paper found with id {paper_id}"},
        )

    cached = get_cached_summary(paper_id=paper_id, tier=tier.value)
    if cached is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error":  "summary_not_found",
                "detail": f"No cached {tier.value} summary for paper {paper_id}. Call POST /summarize to generate one.",
            },
        )

    return SummarizeResponse(
        paper_id=paper_id,
        tier=tier,
        summary_markdown=cached["summary_markdown"],
        from_cache=True,
        created_at=cached["created_at"],
    )