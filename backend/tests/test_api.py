"""
End-to-end HTTP tests using FastAPI's TestClient.

Run from backend/:
    pytest tests/test_api.py -v

Tests that upload papers use `isolated_client` (fresh DB per test).
Tests that only check errors use `client` (shared session client, faster).

For a real Groq call:
    LIVE_GROQ=1 pytest tests/test_api.py::test_full_pipeline_live -v -s
"""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

FIXTURE_PDF = Path(__file__).parent / "fixtures" / "sample.pdf"

# Chunks returned by the mocked retriever — realistic enough for the LLM mock
MOCK_CHUNKS = [
    "This paper introduces the Transformer architecture based on attention.",
    "We achieve 28.4 BLEU on WMT 2014 English-to-German translation.",
]


# ---------------------------------------------------------------------------
# Health check  (uses session client — no DB writes)

def test_health_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# POST /upload  (uses isolated_client — writes to DB)

def test_upload_rejects_non_pdf(isolated_client):
    response = isolated_client.post(
        "/upload",
        files={"file": ("test.txt", b"fake text content", "text/plain")},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "invalid_file_type"


@pytest.mark.skipif(not FIXTURE_PDF.exists(), reason="tests/fixtures/sample.pdf not found")
@patch("app.services.llm._call_groq_async", new_callable=AsyncMock)
def test_upload_pdf_returns_paper_id(mock_groq, isolated_client):
    mock_groq.return_value = "## Summary\n\nMocked summary."
    with open(FIXTURE_PDF, "rb") as f:
        response = isolated_client.post(
            "/upload",
            files={"file": ("sample.pdf", f, "application/pdf")},
        )
    assert response.status_code == 200
    data = response.json()
    assert "paper_id" in data
    assert data["status"] == "ready"
    assert data["num_chunks"] > 0


# ---------------------------------------------------------------------------
# POST /summarize  (uses isolated_client)

def test_summarize_unknown_paper_returns_404(isolated_client):
    response = isolated_client.post(
        "/summarize",
        json={"paper_id": "00000000-0000-0000-0000-000000000000", "tier": "beginner"},
    )
    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "paper_not_found"


def test_summarize_invalid_tier_returns_422(client):
    response = client.post(
        "/summarize",
        json={"paper_id": "any-id", "tier": "ultra"},
    )
    assert response.status_code == 422


@pytest.mark.skipif(not FIXTURE_PDF.exists(), reason="tests/fixtures/sample.pdf not found")
@patch("app.services.retriever.retrieve_chunks", return_value=MOCK_CHUNKS)
@patch("app.services.llm._call_groq_async", new_callable=AsyncMock)
def test_full_upload_then_summarize(mock_groq, mock_retriever, isolated_client):
    """
    Both retriever and Groq are mocked:
      - retriever: avoids downloading the cross-encoder model during tests
      - Groq: avoids real API calls
    """
    mock_groq.return_value = "## Summary\n\nMocked beginner summary."
    with open(FIXTURE_PDF, "rb") as f:
        up = isolated_client.post(
            "/upload",
            files={"file": ("sample.pdf", f, "application/pdf")},
        )
    assert up.status_code == 200
    paper_id = up.json()["paper_id"]

    summ = isolated_client.post(
        "/summarize",
        json={"paper_id": paper_id, "tier": "beginner"},
    )
    assert summ.status_code == 200
    data = summ.json()
    assert data["paper_id"] == paper_id
    assert data["tier"] == "beginner"
    assert len(data["summary_markdown"]) > 10
    assert data["from_cache"] is False


@pytest.mark.skipif(not FIXTURE_PDF.exists(), reason="tests/fixtures/sample.pdf not found")
@patch("app.services.retriever.retrieve_chunks", return_value=MOCK_CHUNKS)
@patch("app.services.llm._call_groq_async", new_callable=AsyncMock)
def test_second_summarize_returns_from_cache(mock_groq, mock_retriever, isolated_client):
    mock_groq.return_value = "## Summary\n\nMocked summary."
    with open(FIXTURE_PDF, "rb") as f:
        up = isolated_client.post(
            "/upload",
            files={"file": ("sample.pdf", f, "application/pdf")},
        )
    paper_id = up.json()["paper_id"]

    # First call — generates and caches
    isolated_client.post("/summarize", json={"paper_id": paper_id, "tier": "intermediate"})

    # Second call — must be from cache, Groq not called again
    r2 = isolated_client.post("/summarize", json={"paper_id": paper_id, "tier": "intermediate"})
    assert r2.status_code == 200
    assert r2.json()["from_cache"] is True
    assert mock_groq.call_count == 1


# ---------------------------------------------------------------------------
# GET /summarize/{paper_id}  (uses isolated_client)

def test_get_summary_unknown_paper_returns_404(isolated_client):
    response = isolated_client.get(
        "/summarize/00000000-0000-0000-0000-000000000000",
        params={"tier": "beginner"},
    )
    assert response.status_code == 404


@pytest.mark.skipif(not FIXTURE_PDF.exists(), reason="tests/fixtures/sample.pdf not found")
@patch("app.services.retriever.retrieve_chunks", return_value=MOCK_CHUNKS)
@patch("app.services.llm._call_groq_async", new_callable=AsyncMock)
def test_get_summary_after_generate(mock_groq, mock_retriever, isolated_client):
    mock_groq.return_value = "## Summary\n\nMocked."
    with open(FIXTURE_PDF, "rb") as f:
        up = isolated_client.post(
            "/upload",
            files={"file": ("sample.pdf", f, "application/pdf")},
        )
    paper_id = up.json()["paper_id"]

    isolated_client.post("/summarize", json={"paper_id": paper_id, "tier": "expert"})

    get_r = isolated_client.get(f"/summarize/{paper_id}", params={"tier": "expert"})
    assert get_r.status_code == 200
    assert get_r.json()["from_cache"] is True
    assert get_r.json()["tier"] == "expert"


# ---------------------------------------------------------------------------
# Live test — real Groq + real retriever, uses quota

@pytest.mark.skipif(
    not (os.getenv("LIVE_GROQ") == "1" and FIXTURE_PDF.exists()),
    reason="Set LIVE_GROQ=1 and provide tests/fixtures/sample.pdf to run",
)
def test_full_pipeline_live(isolated_client):
    with open(FIXTURE_PDF, "rb") as f:
        up = isolated_client.post(
            "/upload",
            files={"file": ("sample.pdf", f, "application/pdf")},
        )
    assert up.status_code == 200
    paper_id = up.json()["paper_id"]
    print(f"\n📄 paper_id: {paper_id}")
    print(f"   title:  {up.json()['title']}")
    print(f"   chunks: {up.json()['num_chunks']}")

    summ = isolated_client.post(
        "/summarize",
        json={"paper_id": paper_id, "tier": "beginner"},
    )
    assert summ.status_code == 200
    print(f"\n📝 Beginner summary (first 300 chars):")
    print(summ.json()["summary_markdown"][:300])