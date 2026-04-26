"""
POST /validate — validate a summary using:
  1. BERTScore F1     — semantic similarity vs abstract (author's intent)
  2. Cosine Similarity — embedding similarity vs full paper (coverage)

No ROUGE. No new dependencies — uses your existing:
  - bert-score       (BERTScore)
  - bge-small-en-v1.5 via sentence-transformers  (CosineSim)
  - ChromaDB         (chunk embeddings already stored)
  - sklearn          (cosine_similarity)
"""

# this is routes/validate.py

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status

from app.models.schema import ValidationRequest, ValidationResponse, Tier

router = APIRouter()

# ---------------------------------------------------------------------------
# Thresholds per tier
# BERTScore  — rescaled [0,1], measures semantic faithfulness to abstract
# CosineSim  — [0,1], measures how well summary covers the full paper

THRESHOLDS: dict[str, dict[str, float]] = {
    "beginner": {
        "bertscore":  0.75,   # simplified language → slightly lower bar
        "cosine_sim": 0.55,   # beginner covers fewer technical areas
    },
    "intermediate": {
        "bertscore":  0.78,
        "cosine_sim": 0.65,
    },
    "expert": {
        "bertscore":  0.80,   # must be semantically faithful to abstract
        "cosine_sim": 0.72,   # must cover the full paper well
    },
}


# ---------------------------------------------------------------------------
# Router

@router.post(
    "/validate",
    response_model=ValidationResponse,
    status_code=status.HTTP_200_OK,
    summary="Validate a summary using BERTScore + Full Paper Cosine Similarity",
    description=(
        "Validates the summary for a given paper+tier using two metrics:\n"
        "1. BERTScore F1 against the abstract — checks semantic faithfulness.\n"
        "2. Cosine similarity against mean-pooled chunk embeddings — checks full paper coverage.\n\n"
        "If no cached summary exists, generates one first (calls Groq). "
        "Results are cached in SQLite."
    ),
    responses={
        404: {"description": "paper_id not found or abstract missing"},
        422: {"description": "Invalid tier"},
        429: {"description": "Groq rate limit hit during generation"},
        500: {"description": "LLM or scoring error"},
    },
)
async def validate_summary(body: ValidationRequest) -> ValidationResponse:

    # ------------------------------------------------------------------
    # 0. Import DB layer
    try:
        from app.db.sqlite import (
            get_paper,
            get_cached_summary,
            cache_summary,
            get_cached_validation,
            cache_validation,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "internal_error", "detail": "DB layer not initialised."},
        ) from exc

    # ------------------------------------------------------------------
    # 1. Paper exists?
    paper = get_paper(body.paper_id)
    if paper is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error":  "paper_not_found",
                "detail": f"No paper found with id {body.paper_id}",
            },
        )

    # ------------------------------------------------------------------
    # 2. Return cached validation if already done
    cached_val = get_cached_validation(paper_id=body.paper_id, tier=body.tier.value)
    if cached_val:
        return ValidationResponse(**cached_val)

    # ------------------------------------------------------------------
    # 3. Get or generate summary
    cached = get_cached_summary(paper_id=body.paper_id, tier=body.tier.value)

    if cached:
        summary_text = cached["summary_markdown"]
    else:
        try:
            from app.services.retriever import retrieve_chunks
            from app.services.llm import generate_summary

            chunks = retrieve_chunks(paper_id=body.paper_id, tier=body.tier.value)
            summary_text = await generate_summary(chunks=chunks, tier=body.tier.value)

            now = datetime.now(timezone.utc)
            try:
                cache_summary(
                    paper_id=body.paper_id,
                    tier=body.tier.value,
                    summary_markdown=summary_text,
                    created_at=now,
                )
            except Exception:
                pass

        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "error":  "generation_failed",
                    "detail": f"Could not generate summary before validation: {exc}",
                },
            ) from exc

    # ------------------------------------------------------------------
    # 4. Extract abstract → BERTScore reference
    abstract_text = _get_abstract(paper)

    # ------------------------------------------------------------------
    # 5. Score

    # Metric 1: BERTScore vs abstract
    bert_f1 = _compute_bertscore(
        candidate=summary_text,
        reference=abstract_text,
    )

    # Metric 2: Cosine similarity vs full paper (ChromaDB embeddings)
    cosine_sim = _compute_fullpaper_similarity(
        paper_id=body.paper_id,
        summary=summary_text,
    )

    # ------------------------------------------------------------------
    # 6. Verdict
    thresholds = THRESHOLDS[body.tier.value]
    metric_pass = {
        "bertscore":  bert_f1    >= thresholds["bertscore"],
        "cosine_sim": cosine_sim >= thresholds["cosine_sim"],
    }
    overall_valid = all(metric_pass.values())

    verdict = _build_verdict(
        tier=body.tier.value,
        bert_f1=bert_f1,
        cosine_sim=cosine_sim,
        metric_pass=metric_pass,
        overall_valid=overall_valid,
        thresholds=thresholds,
    )

    # ------------------------------------------------------------------
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
            paper_id=body.paper_id,
            tier=body.tier.value,
            result=result,
            validated_at=now,
        )
    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------
# Helpers

def _get_abstract(paper: dict) -> str:
    """
    Re-parse the PDF and return the abstract section text.
    Falls back to first 1000 chars of full text if no abstract detected.
    """
    from pathlib import Path

    file_path = paper.get("file_path", "")
    if not file_path or not Path(file_path).exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error":  "pdf_not_found",
                "detail": f"PDF not found at {file_path!r}. Cannot extract abstract.",
            },
        )

    try:
        from app.services.parser import parse_pdf

        parsed   = parse_pdf(file_path)
        sections = parsed.get("sections", [])

        for section in sections:
            if section.get("name", "").lower() == "abstract":
                abstract = section["text"].strip()
                if abstract:
                    return abstract

        # Fallback — no abstract section detected
        full_text = parsed.get("text", "").strip()
        if full_text:
            return full_text[:1000]

        raise ValueError("No text extracted from PDF.")

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error":  "parse_failed",
                "detail": f"Could not extract abstract: {exc}",
            },
        ) from exc


def _compute_bertscore(candidate: str, reference: str) -> float:
    """
    BERTScore F1 — semantic similarity between summary and abstract.
    Uses roberta-large (auto-selected for lang='en').
    rescale_with_baseline=True → normalized to interpretable [0,1] range.
    """
    try:
        from bert_score import score as bert_score

        P, R, F1 = bert_score(
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


def _compute_fullpaper_similarity(paper_id: str, summary: str) -> float:
    """
    Cosine similarity between the summary embedding and the
    mean-pooled embeddings of ALL paper chunks stored in ChromaDB.

    Why mean-pooling:
      - BERTScore has a 512 token limit — can't handle full paper
      - ChromaDB already has every chunk embedded with bge-small-en-v1.5
      - Mean of all chunk vectors = single paper-level semantic vector
      - No token limit, no new dependencies

    Returns float in [0, 1].
    """
    import numpy as np
    from sklearn.metrics.pairwise import cosine_similarity
    from app.db.chroma import get_collection
    from app.services.embeddings import embed_query

    # Pull all chunk embeddings for this paper from ChromaDB
    collection = get_collection()
    results = collection.get(
        where={"paper_id": {"$eq": paper_id}},
        include=["embeddings"],
    )

    embeddings = results.get("embeddings")
    if embeddings is None or len(embeddings) == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error":  "no_embeddings",
                "detail": f"No chunk embeddings found for paper {paper_id} in ChromaDB.",
            },
        )

    # Mean-pool all chunk vectors → one paper-level vector (384-dim for bge-small)
    paper_vec   = np.mean(embeddings, axis=0).reshape(1, -1)

    # Embed the summary using the same bge-small model
    summary_vec = np.array(embed_query(summary)).reshape(1, -1)

    score = cosine_similarity(summary_vec, paper_vec)[0][0]
    return float(score)


def _build_verdict(
    tier: str,
    bert_f1: float,
    cosine_sim: float,
    metric_pass: dict[str, bool],
    overall_valid: bool,
    thresholds: dict[str, float],
) -> str:
    """Human-readable verdict string."""

    icon    = " " if overall_valid else " "
    verdict = f"{icon} Summary is {'VALID' if overall_valid else 'INVALID'} for tier: {tier.upper()}\n\n"

    verdict += "**Metric Breakdown:**\n"
    verdict += (
        f"- BERTScore F1       (vs abstract):   {bert_f1:.4f}  "
        f"(threshold ≥ {thresholds['bertscore']})  "
        f"{' ' if metric_pass['bertscore'] else ' '}\n"
    )
    verdict += (
        f"- Cosine Similarity  (vs full paper): {cosine_sim:.4f}  "
        f"(threshold ≥ {thresholds['cosine_sim']})  "
        f"{' ' if metric_pass['cosine_sim'] else ' '}\n"
    )

    failed = [k for k, v in metric_pass.items() if not v]
    if failed:
        verdict += f"\n**Failed:** {', '.join(failed)}\n"
        if "bertscore" in failed:
            verdict += (
                "\n→ Low BERTScore: summary may be missing key concepts from the abstract."
            )
        if "cosine_sim" in failed:
            verdict += (
                "\n→ Low Cosine Similarity: summary may not cover the full paper well."
            )

    return verdict