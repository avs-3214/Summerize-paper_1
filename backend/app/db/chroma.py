"""
ChromaDB embedded client setup.
"""

import os
import chromadb

CHROMA_DIR = os.getenv("CHROMA_DIR", "../data/chroma")
COLLECTION_NAME = "paper_chunks"

_client = None
_collection = None


def init_chroma():
    """Create the ChromaDB client and collection if they don't exist."""
    global _client, _collection
    os.makedirs(CHROMA_DIR, exist_ok=True)
    _client = chromadb.PersistentClient(path=CHROMA_DIR)
    _collection = _client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )
    print(f"✅ ChromaDB collection '{COLLECTION_NAME}' ready at {CHROMA_DIR}")


def get_collection():
    """Return the collection, initialising if needed."""
    if _collection is None:
        init_chroma()
    return _collection


def store_chunks(paper_id: str, chunks: list[str]):
    """Store text chunks + embeddings will be added by services/embeddings.py."""
    raise NotImplementedError("P3: wire embeddings into store_chunks")