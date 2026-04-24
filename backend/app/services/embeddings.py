"""
Generate embeddings with sentence-transformers (bge-small-en-v1.5) and
store them in ChromaDB — now with section metadata from chunker.

Changes from v1:
  - embed_chunks now accepts the rich chunk dicts from chunk_from_sections()
    and stores section tags in ChromaDB metadata
  - Backward-compat: still accepts plain list[str] via embed_chunks_plain()
"""

from __future__ import annotations
from functools import lru_cache
from sentence_transformers import SentenceTransformer
from app.db.chroma import get_collection

MODEL_NAME = "BAAI/bge-small-en-v1.5"


@lru_cache(maxsize=1)
def _get_model() -> SentenceTransformer:
    print(f"🔄 Loading embedding model {MODEL_NAME}...")
    model = SentenceTransformer(MODEL_NAME)
    print("✅ Embedding model loaded.")
    return model


def embed_chunks(paper_id: str, chunks: list[dict]) -> None:
    """
    Embed section-tagged chunks (output of chunker.chunk_from_sections)
    and store in ChromaDB with section metadata.

    Args:
        paper_id: UUID string
        chunks:   [{"text": str, "section": str, "chunk_index": int}, ...]
    """
    if not chunks:
        return

    model = _get_model()
    texts = [c["text"] for c in chunks]
    embeddings = model.encode(texts, show_progress_bar=False).tolist()

    collection = get_collection()
    collection.upsert(
        ids=[f"{paper_id}_{c['chunk_index']}" for c in chunks],
        documents=texts,
        embeddings=embeddings,
        metadatas=[
            {
                "paper_id":    paper_id,
                "section":     c.get("section", "body"),
                "chunk_index": c["chunk_index"],
            }
            for c in chunks
        ],
    )


def embed_chunks_plain(paper_id: str, chunks: list[str]) -> None:
    """
    Backward-compat: embed plain text strings with no section metadata.
    """
    rich = [{"text": t, "section": "body", "chunk_index": i} for i, t in enumerate(chunks)]
    embed_chunks(paper_id, rich)


def embed_query(query: str) -> list[float]:
    """Embed a single query string. Uses bge instruction prefix for better recall."""
    model = _get_model()
    prefixed = f"Represent this sentence for searching relevant passages: {query}"
    return model.encode(prefixed, show_progress_bar=False).tolist()