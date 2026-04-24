"""
Retrieve relevant chunks from ChromaDB — section-filtered per tier,
then reranked with a cross-encoder for precision.

Improvements over v1:
  - Section-filtered retrieval: each tier queries only the sections that
    matter (beginner → abstract+conclusion, expert → all sections)
  - Cross-encoder reranking: a second-pass ms-marco model reranks the
    bi-encoder candidates by actual relevance to a tier-specific query
  - Pulls 2x candidates then reranks down to top_k (recall-then-precision)

Cross-encoder used: cross-encoder/ms-marco-MiniLM-L-6-v2
  - ~22MB, runs on CPU, adds ~200ms per rerank call
  - Already installed via sentence-transformers
"""

from __future__ import annotations
from functools import lru_cache
from sentence_transformers import CrossEncoder
from app.db.chroma import get_collection
from app.services.embeddings import embed_query

# ---------------------------------------------------------------------------
# Tier config

# How many final chunks to return per tier
TIER_TOP_K: dict[str, int] = {
    "beginner":     3,
    "intermediate": 6,
    "expert":       10,
}

# Sections to INCLUDE per tier (None = no section filter = all sections)
TIER_SECTIONS: dict[str, list[str] | None] = {
    "beginner":     ["abstract", "conclusion", "body"],
    "intermediate": None,   # all sections
    "expert":       None,   # all sections
}

# Tier-specific queries — more targeted than the v1 generic query
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
# Public entry point

def retrieve_chunks(paper_id: str, tier: str) -> list[str]:
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
    top_k     = TIER_TOP_K.get(tier, 5)
    query     = TIER_QUERIES.get(tier, TIER_QUERIES["intermediate"])
    sections  = TIER_SECTIONS.get(tier)

    # Pull 2x candidates so reranker has room to work
    n_candidates = min(top_k * 2, 20)

    query_embedding = embed_query(query)
    collection = get_collection()

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
        # Section filter may have returned nothing (e.g. parser found no abstract)
        # Fall back to unfiltered query
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=n_candidates,
            where={"paper_id": {"$eq": paper_id}},
            include=["documents"],
        )
        candidates = results["documents"][0] if results["documents"] else []

    if not candidates:
        return []

    # Rerank with cross-encoder
    return _rerank(query=query, candidates=candidates, top_k=top_k) 


# ---------------------------------------------------------------------------
# Reranker

def _rerank(query: str, candidates: list[str], top_k: int) -> list[str]:
    """
    Score each (query, candidate) pair with the cross-encoder and
    return the top_k candidates sorted by score descending.
    """
    if len(candidates) <= top_k:
        return candidates
    reranker = _get_reranker()
    scores: list[float] = reranker.predict([(query, doc) for doc in candidates]).tolist()
    ranked = sorted(zip(scores, candidates), key=lambda x: x[0], reverse=True)
    return [doc for _, doc in ranked[:top_k]]