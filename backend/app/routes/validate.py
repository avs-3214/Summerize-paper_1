"""
POST /validate — validate a summary against the paper's abstract
               using ROUGE and BERTScore.

Flow:
  1. Check if paper exists in SQLite
  2. Check if summary is cached → if not, generate it first (calls Groq)
  3. Extract abstract from the PDF via parser
  4. Run ROUGE-1, ROUGE-2, ROUGE-L
  5. Run BERTScore (F1)
  6. Compute verdict (pass/fail per metric + overall)
  7. Cache scores in SQLite
  8. Return ValidationResponse

Dependencies (add to requirements.txt):
    rouge-score>=0.1.2
    bert-score>=0.3.13
    torch>=2.0.0          # bert-score needs torch
"""

# this is routes/validate.py

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status

from app.models.schema import ValidationRequest, ValidationResponse, Tier

router = APIRouter()

# ---------------------------------------------------------------------------
# Thresholds — tuned per tier
# Beginner summaries are shorter/simpler → lower overlap expected
# Expert summaries are dense/technical  → higher semantic bar

THRESHOLDS: dict[str, dict[str, float]] = {
    "beginner": {
        "rouge1":    0.25,   # lower — beginner paraphrases heavily
        "rouge2":    0.08,
        "rougeL":    0.20,
        "bertscore": 0.82,
    },
    "intermediate": {
        "rouge1":    0.35,
        "rouge2":    0.12,
        "rougeL":    0.28,
        "bertscore": 0.84,
    },
    "expert": {
        "rouge1":    0.40,   # expert preserves more technical terms
        "rouge2":    0.18,
        "rougeL":    0.32,
        "bertscore": 0.86,
    },
}


# ---------------------------------------------------------------------------
# Router

@router.post(
    "/validate",
    response_model=ValidationResponse,
    status_code=status.HTTP_200_OK,
    summary="Validate a summary against the paper abstract",
    description=(
        "If a cached summary exists for the paper+tier, validates it immediately. "
        "If not, generates the summary first (calling Groq), then validates. "
        "Scores are cached in SQLite for future retrieval. "
        "Reference text = abstract section extracted by the parser."
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
    # 2. Return cached validation scores if available
    cached_val = get_cached_validation(paper_id=body.paper_id, tier=body.tier.value)
    if cached_val:
        return ValidationResponse(**cached_val)

    # ------------------------------------------------------------------
    # 3. Get or generate summary
    cached = get_cached_summary(paper_id=body.paper_id, tier=body.tier.value)

    if cached:
        summary_text = cached["summary_markdown"]
    else:
        # Auto-generate then cache
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
                pass  # best-effort cache

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
    # 4. Extract abstract from PDF (reference text)
    abstract_text = _get_abstract(paper)   # raises 404 if missing

    # ------------------------------------------------------------------
    # 5. Score
    rouge_scores = _compute_rouge(
        candidate=summary_text,
        reference=abstract_text,
    )
    bert_f1 = _compute_bertscore(
        candidate=summary_text,
        reference=abstract_text,
    )

    # ------------------------------------------------------------------
    # 6. Verdict
    thresholds = THRESHOLDS[body.tier.value]
    metric_pass = {
        "rouge1":    rouge_scores["rouge1"]    >= thresholds["rouge1"],
        "rouge2":    rouge_scores["rouge2"]    >= thresholds["rouge2"],
        "rougeL":    rouge_scores["rougeL"]    >= thresholds["rougeL"],
        "bertscore": bert_f1                   >= thresholds["bertscore"],
    }
    overall_valid = all(metric_pass.values())

    # Human-readable verdict message
    verdict_msg = _build_verdict_message(
        tier=body.tier.value,
        rouge_scores=rouge_scores,
        bert_f1=bert_f1,
        metric_pass=metric_pass,
        overall_valid=overall_valid,
        thresholds=thresholds,
    )

    # ------------------------------------------------------------------
    # 7. Cache validation result
    now = datetime.now(timezone.utc)
    result = ValidationResponse(
        paper_id=body.paper_id,
        tier=body.tier,
        rouge1=round(rouge_scores["rouge1"], 4),
        rouge2=round(rouge_scores["rouge2"], 4),
        rougeL=round(rouge_scores["rougeL"], 4),
        bertscore_f1=round(bert_f1, 4),
        thresholds=thresholds,
        metric_pass=metric_pass,
        overall_valid=overall_valid,
        verdict=verdict_msg,
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
        pass  # best-effort

    return result


# ---------------------------------------------------------------------------
# Helpers

def _get_abstract(paper: dict) -> str:
    """
    Re-parse the PDF stored at paper['file_path'] and return the abstract text.
    Falls back to first 1000 chars of full text if abstract section not found.

    Raises HTTPException(404) if PDF is missing or completely unparseable.
    """
    from pathlib import Path

    file_path = paper.get("file_path", "")
    if not file_path or not Path(file_path).exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error":  "pdf_not_found",
                "detail": (
                    f"PDF file not found at {file_path!r}. "
                    "Cannot extract abstract for validation."
                ),
            },
        )

    try:
        from app.services.parser import parse_pdf

        parsed = parse_pdf(file_path)
        sections = parsed.get("sections", [])

        # Try to find the abstract section
        for section in sections:
            if section.get("name", "").lower() == "abstract":
                abstract = section["text"].strip()
                if abstract:
                    return abstract

        # Fallback: no abstract section detected → use first 1000 chars of full text
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
                "detail": f"Could not extract abstract from PDF: {exc}",
            },
        ) from exc


def _compute_rouge(candidate: str, reference: str) -> dict[str, float]:
    """
    Compute ROUGE-1, ROUGE-2, ROUGE-L F1 scores.
    Returns dict with keys: rouge1, rouge2, rougeL
    """
    try:
        from rouge_score import rouge_scorer

        scorer = rouge_scorer.RougeScorer(
            ["rouge1", "rouge2", "rougeL"],
            use_stemmer=True,   # 'summarise' == 'summarize', etc.
        )
        scores = scorer.score(target=reference, prediction=candidate)

        return {
            "rouge1": scores["rouge1"].fmeasure,
            "rouge2": scores["rouge2"].fmeasure,
            "rougeL": scores["rougeL"].fmeasure,
        }

    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error":  "missing_dependency",
                "detail": "rouge-score not installed. Run: pip install rouge-score",
            },
        )


def _compute_bertscore(candidate: str, reference: str) -> float:
    """
    Compute BERTScore F1 between candidate summary and reference (abstract).
    Uses microsoft/deberta-xlarge-mnli model (best quality, ~900MB).
    Falls back to roberta-large if deberta unavailable.

    Returns F1 as a float.
    """
    try:
        from bert_score import score as bert_score

        # lang="en" auto-selects roberta-large for English
        # rescale_with_baseline=True maps scores to [0,1] range — more interpretable
        P, R, F1 = bert_score(
            cands=[candidate],
            refs=[reference],
            lang="en",
            rescale_with_baseline=True,
            verbose=False,
        )
        return float(F1[0])

    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error":  "missing_dependency",
                "detail": "bert-score not installed. Run: pip install bert-score",
            },
        )


def _build_verdict_message(
    tier: str,
    rouge_scores: dict[str, float],
    bert_f1: float,
    metric_pass: dict[str, bool],
    overall_valid: bool,
    thresholds: dict[str, float],
) -> str:
    """Build a human-readable verdict string for the response."""

    status_icon = "✅" if overall_valid else "❌"
    verdict = f"{status_icon} Summary is {'VALID' if overall_valid else 'INVALID'} for tier: {tier.upper()}\n\n"

    verdict += "**Metric Breakdown:**\n"
    verdict += f"- ROUGE-1:    {rouge_scores['rouge1']:.4f}  (threshold ≥ {thresholds['rouge1']})  {'✅' if metric_pass['rouge1'] else '❌'}\n"
    verdict += f"- ROUGE-2:    {rouge_scores['rouge2']:.4f}  (threshold ≥ {thresholds['rouge2']})  {'✅' if metric_pass['rouge2'] else '❌'}\n"
    verdict += f"- ROUGE-L:    {rouge_scores['rougeL']:.4f}  (threshold ≥ {thresholds['rougeL']})  {'✅' if metric_pass['rougeL'] else '❌'}\n"
    verdict += f"- BERTScore:  {bert_f1:.4f}  (threshold ≥ {thresholds['bertscore']})  {'✅' if metric_pass['bertscore'] else '❌'}\n"

    failed = [k for k, v in metric_pass.items() if not v]
    if failed:
        verdict += f"\n**Failed metrics:** {', '.join(failed)}\n"
        verdict += (
            "\nNote: Low ROUGE scores may indicate the summary paraphrases heavily "
            "(acceptable for beginner tier). Low BERTScore indicates semantic drift — "
            "the summary may be missing key concepts from the abstract."
        )

    return verdict
