"""
POST /query — answer a specific question about a paper at a chosen tier.

How this differs from /summarize:
  - The user's question drives ChromaDB retrieval (not a fixed tier query)
  - Tier controls depth of explanation, not what sections are retrieved
  - Cache key is sha256(question+tier) — same question at different tiers caches separately
  - No map-reduce — query answers are always a single focused Groq call
"""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from app.models.schema import QueryRequest, QueryResponse

router = APIRouter()


@router.post(
    "/query",
    response_model=QueryResponse,
    status_code=status.HTTP_200_OK,
    summary="Answer a specific question about a paper at a chosen depth",
    description=(
        "Uses the question as the semantic retrieval query to find the most "
        "relevant chunks, then answers at the requested tier depth. "
        "Beginner gives plain-language answers, expert gives technical detail. "
        "Results are cached by (paper_id, question, tier)."
    ),
    responses={
        404: {"description": "paper_id not found"},
        422: {"description": "question too short/long or invalid tier"},
        429: {"description": "Groq rate limit — includes retry_after"},
        500: {"description": "LLM or internal error"},
    },
)
async def query_paper(body: QueryRequest) -> QueryResponse:
    # 1. Paper exists?
    try:
        from app.db.sqlite import get_paper, get_cached_query, cache_query_result
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "internal_error", "detail": "DB layer not initialised."},
        ) from exc

    paper = get_paper(body.paper_id)
    if paper is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "paper_not_found", "detail": f"No paper found with id {body.paper_id}"},
        )

    # 2. Cache check
    cached = get_cached_query(
        paper_id=body.paper_id,
        question=body.question,
        tier=body.tier.value,
    )
    if cached:
        return QueryResponse(
            paper_id=body.paper_id,
            question=body.question,
            tier=body.tier,
            answer_markdown=cached["answer_markdown"],
            from_cache=True,
            created_at=cached["created_at"],
        )

    # 3. Retrieve chunks using question as the semantic query
    try:
        from app.services.retriever import retrieve_chunks_for_query
        from app.services.llm import generate_query_answer, QUERY_TOP_K

        top_k  = QUERY_TOP_K[body.tier.value]
        chunks = retrieve_chunks_for_query(
            paper_id=body.paper_id,
            question=body.question,
            top_k=top_k,
        )

        # 4. Generate answer
        answer_markdown = await generate_query_answer(
            chunks=chunks,
            question=body.question,
            tier=body.tier.value,
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "llm_error", "detail": f"Query failed: {exc}"},
        ) from exc

    # 5. Cache result (best-effort)
    now = datetime.now(timezone.utc)
    try:
        cache_query_result(
            paper_id=body.paper_id,
            question=body.question,
            tier=body.tier.value,
            answer_markdown=answer_markdown,
            created_at=now,
        )
    except Exception:
        pass

    return QueryResponse(
        paper_id=body.paper_id,
        question=body.question,
        tier=body.tier,
        answer_markdown=answer_markdown,
        from_cache=False,
        created_at=now,
    )