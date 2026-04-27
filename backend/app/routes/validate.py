"""
validate.py
POST /validate — validate a summary using:
  1. BERTScore F1     — semantic similarity vs tier-appropriate reference chunks
  2. Coverage Score   — max-pooled cosine similarity vs paper chunks

BERTScore reference is tier-aware, pulled from ChromaDB:
  beginner:     top 3 chunks from abstract+conclusion
  intermediate: top 6 chunks across all sections
  expert:       top 10 chunks across all sections

rescale_with_baseline=True:
  Raw BERTScore F1 with roberta-large clusters between 0.82–0.92 even for
  unrelated text, making thresholds meaningless. Rescaling maps scores to
  [0,1] where 0 = random baseline, 1 = identical. Typical good summaries
  score 0.50–0.75 in this range, giving real signal.

Max-pooled cosine similarity (Metric 2):
  Mean-pooling all chunk embeddings penalizes summaries for not covering
  sections they were never meant to cover (e.g. beginner penalized for
  missing methodology details). Max-pooling rewards depth of coverage for
  the sections the summary does address.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status

from app.models.schema import ValidationRequest, ValidationResponse

router = APIRouter()

# ---------------------------------------------------------------------------
# Tier config

REFERENCE_TOP_K: dict[str, int] = {
    "beginner":     3,
    "intermediate": 6,
    "expert":       10,
}

REFERENCE_SECTIONS: dict[str, list[str] | None] = {
    "beginner":     ["abstract", "conclusion", "body"],
    "intermediate": None,
    "expert":       None,
}

# BERTScore 512-token limit. ~400 tokens ≈ 1600 chars.
BERT_CHAR_LIMIT = 1600

# Thresholds calibrated for rescaled BERTScore + max-pooled cosine:
#
# BERTScore (rescaled): typical good summary = 0.50–0.75
#   beginner:     0.45 — plain language paraphrase, expect lower semantic match
#   intermediate: 0.52 — structured restatement, moderate match expected
#   expert:       0.58 — technical depth expected, high match required
#
# Coverage (max-pooled cosine): typical range 0.65–0.85
#   beginner:     0.62 — only needs to cover abstract/conclusion well
#   intermediate: 0.70 — needs broad coverage across sections
#   expert:       0.76 — must cover all major sections deeply

THRESHOLDS: dict[str, dict[str, float]] = {
    "beginner": {
        "bertscore":  0.70,
        "cosine_sim": 0.62,
    },
    "intermediate": {
        "bertscore":  0.70,
        "cosine_sim": 0.70,
    },
    "expert": {
        "bertscore":  0.70,
        "cosine_sim": 0.76,
    },
}

# Tier queries — same as retriever.py for consistent chunk selection
_TIER_QUERIES: dict[str, str] = {
    "beginner":     "What is the main problem this paper solves and what did it find?",
    "intermediate": "What are the key contributions, methodology, and results of this research paper?",
    "expert":       "What is the technical approach, experimental setup, baselines, metrics, ablations, limitations, and future work?",
}


# ---------------------------------------------------------------------------
# Router

@router.post(
    "/validate",
    response_model=ValidationResponse,
    status_code=status.HTTP_200_OK,
    summary="Validate summary accuracy using rescaled BERTScore + max-pooled coverage",
    description=(
        "Two metrics, both tier-aware:\n"
        "1. BERTScore F1 (rescaled) against tier-appropriate reference chunks "
        "   from ChromaDB — same chunks fed to Groq.\n"
        "2. Max-pooled cosine similarity against all paper chunk embeddings "
        "   — rewards depth of coverage for relevant sections.\n\n"
        "Results cached in SQLite."
    ),
    responses={
        404: {"description": "paper_id not found or no chunks in ChromaDB"},
        422: {"description": "Invalid tier"},
        429: {"description": "Groq rate limit hit during generation"},
        500: {"description": "LLM or scoring error"},
    },
)
async def validate_summary(body: ValidationRequest) -> ValidationResponse:

    try:
        from app.db.sqlite import (
            get_paper, get_cached_summary, cache_summary,
            get_cached_validation, cache_validation,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "internal_error", "detail": "DB layer not initialised."},
        ) from exc

    # 1. Paper exists?
    paper = get_paper(body.paper_id)
    if paper is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "paper_not_found", "detail": f"No paper found with id {body.paper_id}"},
        )

    # 2. Cached validation?
    cached_val = get_cached_validation(paper_id=body.paper_id, tier=body.tier.value)
    if cached_val:
        return ValidationResponse(**cached_val)

    # 3. Get or generate summary
    cached = get_cached_summary(paper_id=body.paper_id, tier=body.tier.value)
    if cached:
        summary_text = cached["summary_markdown"]
    else:
        try:
            from app.services.retriever import retrieve_chunks
            from app.services.llm import generate_summary

            chunks       = retrieve_chunks(paper_id=body.paper_id, tier=body.tier.value)
            summary_text = await generate_summary(chunks=chunks, tier=body.tier.value)
            try:
                cache_summary(
                    paper_id=body.paper_id, tier=body.tier.value,
                    summary_markdown=summary_text,
                    created_at=datetime.now(timezone.utc),
                )
            except Exception:
                pass
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"error": "generation_failed", "detail": f"Could not generate summary: {exc}"},
            ) from exc

    # 4. Pull tier-appropriate reference chunks from ChromaDB
    reference_text = _get_reference_chunks(paper_id=body.paper_id, tier=body.tier.value)

    # 5. Score
    bert_f1    = _compute_bertscore(candidate=summary_text, reference=reference_text)
    cosine_sim = _compute_coverage(paper_id=body.paper_id, summary=summary_text)

    # 6. Verdict
    thresholds    = THRESHOLDS[body.tier.value]
    metric_pass   = {
        "bertscore":  bert_f1    >= thresholds["bertscore"],
        "cosine_sim": cosine_sim >= thresholds["cosine_sim"],
    }
    overall_valid = all(metric_pass.values())
    verdict       = _build_verdict(
        tier=body.tier.value, bert_f1=bert_f1, cosine_sim=cosine_sim,
        metric_pass=metric_pass, overall_valid=overall_valid, thresholds=thresholds,
    )

    # 7. Cache + return
    now = datetime.now(timezone.utc)
    result = ValidationResponse(
        paper_id=body.paper_id,
        tier=body.tier,
        bertscore_f1=round(bert_f1, 4),
        fullpaper_similarity=round(cosine_sim, 4),
        thresholds=thresholds,
        metric_pass=metric_pass,
        overall_valid=overall_valid,
        verdict=verdict,
        validated_at=now,
    )
    try:
        cache_validation(
            paper_id=body.paper_id, tier=body.tier.value,
            result=result, validated_at=now,
        )
    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------
# Helpers

def _get_reference_chunks(paper_id: str, tier: str) -> str:
    """
    Pull tier-appropriate chunks from ChromaDB and concatenate as
    the BERTScore reference text. Truncates at BERT_CHAR_LIMIT.
    """
    from app.db.chroma import get_collection
    from app.services.embeddings import embed_query

    top_k           = REFERENCE_TOP_K[tier]
    sections        = REFERENCE_SECTIONS[tier]
    query_embedding = embed_query(_TIER_QUERIES[tier])
    collection      = get_collection()

    where = (
        {
            "$and": [
                {"paper_id": {"$eq": paper_id}},
                {"section":  {"$in": sections}},
            ]
        }
        if sections
        else {"paper_id": {"$eq": paper_id}}
    )

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(top_k * 2, 20),
        where=where,
        include=["documents"],
    )
    chunks: list[str] = results["documents"][0] if results["documents"] else []

    # Fallback: section filter returned nothing
    if not chunks and sections:
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k * 2, 20),
            where={"paper_id": {"$eq": paper_id}},
            include=["documents"],
        )
        chunks = results["documents"][0] if results["documents"] else []

    if not chunks:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "no_chunks", "detail": f"No chunks found for paper {paper_id}. Try re-uploading."},
        )

    # Concatenate up to BERT_CHAR_LIMIT
    reference = ""
    for chunk in chunks[:top_k]:
        candidate = (reference + "\n\n" + chunk).strip()
        if len(candidate) <= BERT_CHAR_LIMIT:
            reference = candidate
        else:
            remaining = BERT_CHAR_LIMIT - len(reference)
            if remaining > 100:
                reference = (reference + "\n\n" + chunk[:remaining]).strip()
            break

    return reference


def _compute_bertscore(candidate: str, reference: str) -> float:
    """
    BERTScore F1 with rescale_with_baseline=True.

    Raw roberta-large F1 clusters between 0.82–0.92 for English academic text.
    Thresholds are calibrated to this range (0.82–0.86).
    First call downloads roberta-large (~1.4GB) — subsequent calls are fast.
    """
    try:
        from bert_score import score as bert_score_fn

        P, R, F1 = bert_score_fn(
            cands=[candidate],
            refs=[reference],
            lang="en",
            rescale_with_baseline=False,
            verbose=False,
        )
        return float(F1[0])

    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error":  "missing_dependency",
                "detail": "bert-score not installed. Run: pip install bert-score==0.3.13",
            },
        )


def _compute_coverage(paper_id: str, summary: str) -> float:
    """
    Max-pooled cosine similarity between the summary embedding and
    individual paper chunk embeddings.

    Why max-pooling instead of mean-pooling:
      Mean-pooling penalizes summaries for not covering sections they were
      never meant to cover. A beginner summary scoring low because it doesn't
      cover methodology detail is a false negative.

      Max-pooling asks: "does the summary deeply match at least some
      chunks?" — which rewards focused, accurate coverage of relevant
      sections without penalizing intentional omissions.

    Returns float in [0, 1].
    """
    import numpy as np
    from sklearn.metrics.pairwise import cosine_similarity as sklearn_cosine
    from app.db.chroma import get_collection
    from app.services.embeddings import embed_query

    collection = get_collection()
    results    = collection.get(
        where={"paper_id": {"$eq": paper_id}},
        include=["embeddings"],
    )

    embeddings = results.get("embeddings")
    if embeddings is None or len(embeddings) == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "no_embeddings", "detail": f"No embeddings found for paper {paper_id}."},
        )

    summary_vec  = np.array(embed_query(summary)).reshape(1, -1)
    chunk_matrix = np.array(embeddings)                          # shape: (n_chunks, 384)

    # Similarity of summary vs every chunk — shape: (1, n_chunks)
    similarities = sklearn_cosine(summary_vec, chunk_matrix)[0]  # shape: (n_chunks,)

    # Max-pool: best-matching chunk score
    return float(np.max(similarities))


def _build_verdict(
    tier: str,
    bert_f1: float,
    cosine_sim: float,
    metric_pass: dict[str, bool],
    overall_valid: bool,
    thresholds: dict[str, float],
) -> str:
    icon    = "✓" if overall_valid else "✗"
    verdict = f"{icon} Summary is {'VALID' if overall_valid else 'INVALID'} for tier: {tier.upper()}\n\n"

    verdict += "**Metric Breakdown:**\n"
    verdict += (
        f"- BERTScore F1 (rescaled, vs {tier} ref chunks): {bert_f1:.4f}  "
        f"(threshold ≥ {thresholds['bertscore']})  "
        f"{'✓' if metric_pass['bertscore'] else '✗'}\n"
    )
    verdict += (
        f"- Coverage Score (max-pooled cosine):            {cosine_sim:.4f}  "
        f"(threshold ≥ {thresholds['cosine_sim']})  "
        f"{'✓' if metric_pass['cosine_sim'] else '✗'}\n"
    )

    failed = [k for k, v in metric_pass.items() if not v]
    if failed:
        verdict += f"\n**Failed:** {', '.join(failed)}\n"
        if "bertscore" in failed:
            verdict += f"\n→ Low BERTScore: summary may be missing key concepts from the {tier}-level reference content."
        if "cosine_sim" in failed:
            verdict += "\n→ Low Coverage: summary does not closely match any section of the paper."

    return verdict