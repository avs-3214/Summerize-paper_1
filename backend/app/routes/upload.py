"""
POST /upload — accepts a PDF, parses it, chunks it, embeds it, stores metadata.
"""

import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.models.schema import UploadResponse, PaperStatus

router = APIRouter()

# Absolute max file size: 50 MB
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024
UPLOAD_DIR = Path("../data/uploads")


@router.post(
    "/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_200_OK,
    summary="Upload a PDF paper",
    description=(
        "Accepts a PDF file via multipart/form-data. "
        "Parses, chunks, and embeds the paper. "
        "Returns a paper_id to use in /summarize once status is 'ready'."
    ),
    responses={
        400: {"description": "Invalid file type or file too large"},
        422: {"description": "PDF could not be parsed"},
        500: {"description": "Internal server error"},
    },
)
async def upload_paper(file: UploadFile = File(...)) -> UploadResponse:
    """
    Pipeline (all synchronous for now — fast enough for a hackathon):
      1. Validate file type + size
      2. Save to data/uploads/
      3. Parse with PyMuPDF4LLM        → services/parser.py
      4. Chunk text                    → services/chunker.py
      5. Generate embeddings           → services/embeddings.py
      6. Store chunks in ChromaDB      → db/chroma.py
      7. Store metadata in SQLite      → db/sqlite.py
      8. Return UploadResponse
    """

    # ------------------------------------------------------------------
    # 1. Validate file type

    if file.content_type != "application/pdf":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_file_type", "detail": "Only PDF files are accepted."},
        )

    # ------------------------------------------------------------------
    # 2. Read bytes + size check

    raw_bytes = await file.read()
    if len(raw_bytes) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "file_too_large",
                "detail": f"File exceeds the 50 MB limit ({len(raw_bytes) // (1024*1024)} MB received).",
            },
        )

    # ------------------------------------------------------------------
    # 3. Save to disk (needed by PyMuPDF4LLM which works on file paths)

    paper_id = str(uuid.uuid4())
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    saved_path = UPLOAD_DIR / f"{paper_id}.pdf"
    saved_path.write_bytes(raw_bytes)

    # ------------------------------------------------------------------
    # 4–7. Ingestion pipeline
    # Import inside the function so that missing deps surface as 500s
    # rather than crashing the whole app at startup during beginning.
    # Replace these stubs with real implementations.

    try:
        from app.services.parser import parse_pdf
        from app.services.chunker import chunk_text
        from app.services.embeddings import embed_chunks
        from app.db.chroma import store_chunks
        from app.db.sqlite import store_paper_metadata

        # parse
        parsed = parse_pdf(str(saved_path))          # returns {"title": str, "text": str}
        title: str = parsed.get("title") or (file.filename or "Untitled Paper")

        # chunk
        chunks: list[str] = chunk_text(parsed["text"])

        # embed + store in ChromaDB
        embed_chunks(paper_id=paper_id, chunks=chunks)

        # store metadata in SQLite
        store_paper_metadata(
            paper_id=paper_id,
            title=title,
            num_chunks=len(chunks),
            file_path=str(saved_path),
        )

    except NotImplementedError:
        # Services not yet implemented — return a stub response so
        # P4 can work against the API shape before P1/P3 finish.
        title = file.filename or "Untitled Paper"
        chunks = []

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "parse_failed", "detail": f"Could not parse PDF: {exc}"},
        ) from exc

    # ------------------------------------------------------------------
    # 8. Return

    return UploadResponse(
        paper_id=paper_id,
        title=title,
        num_chunks=len(chunks),
        status=PaperStatus.ready,
    )