"""
Shared pytest configuration and fixtures.

Why this file is needed:
  1. Env vars must be set BEFORE any app module imports — conftest.py is
     the earliest hook pytest gives us. Without this, AsyncGroq and the
     DB layer crash at import time because GROQ_API_KEY / paths are missing.
  2. Isolated DB per test — each test that touches SQLite or ChromaDB gets
     a fresh temp directory, so a paper uploaded in test A cannot affect test B.
  3. Single TestClient shared across the session for cheap tests that don't
     need isolation (health check, 404s, 422s).
"""

import os
import shutil
import tempfile

import pytest

# ---------------------------------------------------------------------------
# Env vars — set before ANY app code is imported.
# os.environ.setdefault only sets if not already present, so a real .env
# loaded externally (e.g. for LIVE_GROQ=1 tests) still takes precedence.

os.environ.setdefault("GROQ_API_KEY", "test_key_not_real")
os.environ.setdefault("MODEL_BEGINNER", "llama-3.1-8b-instant")
os.environ.setdefault("MODEL_ADVANCED", "llama-3.3-70b-versatile")

# Point DB paths at /tmp so tests never touch the real data/ directory
os.environ.setdefault("CHROMA_DIR", "/tmp/test_chroma_default")
os.environ.setdefault("SQLITE_DB",  "/tmp/test_papers_default.db")


# ---------------------------------------------------------------------------
# Session-scoped client — for tests that don't write to DB
# (health check, validation errors, 404s on unknown IDs)

@pytest.fixture(scope="session")
def client():
    """
    A single TestClient for the whole test session.
    Use this for read-only / error-path tests that don't upload papers.
    """
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Function-scoped isolated client — for tests that write to DB
# (upload + summarize flows)
#
# Each test gets:
#   - a fresh temp directory for ChromaDB
#   - a fresh temp file path for SQLite (file created on first init_db())
#   - a fresh TestClient so the lifespan hook re-runs against those paths
#
# The temp dir is deleted after the test finishes.

@pytest.fixture()
def isolated_client(tmp_path):
    """
    A TestClient backed by a clean, isolated DB for this test only.
    Use this for any test that calls POST /upload or POST /summarize.

    Usage:
        def test_something(isolated_client):
            response = isolated_client.post("/upload", ...)
    """
    chroma_dir = str(tmp_path / "chroma")
    sqlite_db  = str(tmp_path / "papers.db")

    # Override env vars for this test
    os.environ["CHROMA_DIR"] = chroma_dir
    os.environ["SQLITE_DB"]  = sqlite_db

    # Re-initialise the DB singletons with the new paths
    # (they may have been initialised by a previous test)
    _reset_db_singletons()

    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        yield c

    # Restore defaults so session-scoped client is unaffected
    os.environ["CHROMA_DIR"] = "/tmp/test_chroma_default"
    os.environ["SQLITE_DB"]  = "/tmp/test_papers_default.db"
    _reset_db_singletons()


def _reset_db_singletons():
    """
    Force the ChromaDB and SQLAlchemy singletons to re-initialise
    on next access. Needed because both modules cache their clients
    at module level.
    """
    # Reset ChromaDB singleton
    try:
        import app.db.chroma as chroma_mod
        chroma_mod._client     = None
        chroma_mod._collection = None
    except ImportError:
        pass

    # Reset SQLAlchemy engine so it picks up the new SQLITE_DB path
    try:
        import app.db.sqlite as sqlite_mod
        sqlite_mod.engine = sqlite_mod.create_engine(
            f"sqlite:///{os.environ['SQLITE_DB']}",
            connect_args={"check_same_thread": False},
        )
        sqlite_mod.SessionLocal = sqlite_mod.sessionmaker(
            bind=sqlite_mod.engine, autocommit=False, autoflush=False
        )
        sqlite_mod.Base.metadata.create_all(bind=sqlite_mod.engine)
    except ImportError:
        pass