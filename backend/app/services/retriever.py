"""
Retrieve relevant chunks from ChromaDB — section-filtered per tier,
then reranked with a cross-encoder for precision.
<<<<<<< HEAD
=======

Changes over v2:
  - expert top_k increased 10 → 15
    Rationale: expert summaries require 7 sections. With 800-char chunks,
    10 chunks gave ~1500 words of context — not enough for the LLM to fill
    all 7 sections without hallucinating. 15 chunks gives ~2500 words.
  - n_candidates cap raised 20 → 30 to keep the 2x recall ratio intact
    for the new top_k=15 (15*2=30).
  - All other logic unchanged.

Cross-encoder used: cross-encoder/ms-marco-MiniLM-L-6-v2
  - ~22MB, runs on CPU, adds ~200ms per rerank call
  - Already installed via sentence-transformers
>>>>>>> e0c39c48 (my local changes)
"""

from __future__ import annotations
from functools import lru_cache
from sentence_transformers import CrossEncoder
from app.db.chroma import get_collection
from app.services.embeddings import embed_query

# ---------------------------------------------------------------------------
# Tier config

TIER_TOP_K: dict[str, int] = {
    "beginner":     3,
    "intermediate": 6,
    "expert":       15,   # was 10 — gives ~2500 words of context for 7-section summary
}

TIER_SECTIONS: dict[str, list[str] | None] = {
    "beginner":     ["abstract", "conclusion", "body"],
    "intermediate": None,
    "expert":       None,
}

TIER_QUERIES: dict[str, str] = {
    "beginner": (
        "What is the main problem this paper solves and what did it find?"
    ),
    "intermediate": (
        "What are the key contributions, methodology, and results of this research paper?"
    ),
    "expert": (
        "What is the technical approach, experimental setup, baselines, metrics, "
        "ablations, limitations, and future work of this paper?"
    ),
}

RERANK_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"


@lru_cache(maxsize=1)
def _get_reranker() -> CrossEncoder:
    print(f"🔄 Loading reranker {RERANK_MODEL_NAME}...")
    model = CrossEncoder(RERANK_MODEL_NAME)
    print("✅ Reranker loaded.")
    return model


# ---------------------------------------------------------------------------
# Standard tier-based retrieval (used by /summarize)

def retrieve_chunks(paper_id: str, tier: str) -> list[str]:
<<<<<<< HEAD
    top_k        = TIER_TOP_K.get(tier, 5)
    query        = TIER_QUERIES.get(tier, TIER_QUERIES["intermediate"])
    sections     = TIER_SECTIONS.get(tier)
    n_candidates = min(top_k * 2, 20)
=======
    """
    Retrieve the most relevant chunks for this paper + tier.

    Pipeline:
      1. Embed tier-specific query
      2. Query ChromaDB with section filter (2x candidates for reranking)
      3. Rerank with cross-encoder
      4. Return top_k texts

    Args:
        paper_id: UUID string
        tier:     "beginner" | "intermediate" | "expert"

    Returns:
        List of chunk text strings, best-first.
    """
    top_k    = TIER_TOP_K.get(tier, 5)
    query    = TIER_QUERIES.get(tier, TIER_QUERIES["intermediate"])
    sections = TIER_SECTIONS.get(tier)

    # Pull 2x candidates so reranker has room to work.
    # Cap raised to 30 (was 20) to cover expert top_k=15 at 2x ratio.
    n_candidates = min(top_k * 2, 30)
>>>>>>> e0c39c48 (my local changes)

    query_embedding = embed_query(query)
    collection      = get_collection()

    # ------------------------------------------------------------------
    # ChromaDB where filter
    # Multiple conditions MUST use $and — top-level dict only allows
    # a single field. Two fields at top level raises:
    # "Expected where to have exactly one operator"

    if sections:
        where = {
            "$and": [
                {"paper_id": {"$eq": paper_id}},
                {"section":  {"$in": sections}},
            ]
        }
    else:
        where = {"paper_id": {"$eq": paper_id}}

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_candidates,
        where=where,
        include=["documents"],
    )
    candidates: list[str] = results["documents"][0] if results["documents"] else []

    if not candidates and sections:
        # Section filter may have returned nothing (e.g. parser found no abstract).
        # Fall back to unfiltered query.
        print(f"[retriever] Section filter returned no results for tier='{tier}', "
              f"paper_id='{paper_id}'. Falling back to unfiltered query.")
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=n_candidates,
            where={"paper_id": {"$eq": paper_id}},
            include=["documents"],
        )
        candidates = results["documents"][0] if results["documents"] else []

    if not candidates:
        print(f"[retriever] WARNING: No candidates found for paper_id='{paper_id}', "
              f"tier='{tier}'.")
        return []

    print(f"[retriever] {len(candidates)} candidates retrieved for tier='{tier}', "
          f"reranking to top {top_k}.")

    # Rerank with cross-encoder
    return _rerank(query=query, candidates=candidates, top_k=top_k)


# ---------------------------------------------------------------------------
# Question-driven retrieval (used by /query)

def retrieve_chunks_for_query(paper_id: str, question: str, top_k: int) -> list[str]:
    """
    Retrieve chunks using the user's question as the semantic query.
    No section filter — searches all chunks so no relevant content is excluded.
    Reranks with cross-encoder before returning.

    Args:
        paper_id: UUID string
        question: Raw user question string
        top_k:    Number of chunks to return after reranking
    """
    n_candidates    = min(top_k * 2, 20)
    query_embedding = embed_query(question)
    collection      = get_collection()

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_candidates,
        where={"paper_id": {"$eq": paper_id}},
        include=["documents"],
    )
    candidates: list[str] = results["documents"][0] if results["documents"] else []

    if not candidates:
        return []

    return _rerank(query=question, candidates=candidates, top_k=top_k)


# ---------------------------------------------------------------------------
# Reranker

def _rerank(query: str, candidates: list[str], top_k: int) -> list[str]:
    if len(candidates) <= top_k:
        return candidates
    reranker = _get_reranker()
    scores: list[float] = reranker.predict([(query, doc) for doc in candidates]).tolist()
    ranked = sorted(zip(scores, candidates), key=lambda x: x[0], reverse=True)
    return [doc for _, doc in ranked[:top_k]]