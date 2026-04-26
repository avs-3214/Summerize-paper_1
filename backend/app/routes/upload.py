"""
POST /upload — accepts a PDF, parses it, chunks it, embeds it, stores metadata.

Changes from v1:
  - Uses chunk_from_sections() instead of chunk_text() — section-aware chunking
  - Passes rich chunk dicts to embed_chunks() so section tags are stored in ChromaDB
  - Stores sections count in metadata for debugging
"""
#this is upload.py
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.models.schema import UploadResponse, PaperStatus

router = APIRouter()

MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024
UPLOAD_DIR = Path("../data/uploads")


@router.post(
    "/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_200_OK,
    summary="Upload a PDF paper",
)
async def upload_paper(file: UploadFile = File(...)) -> UploadResponse:
    # 1. Validate file type
    if file.content_type != "application/pdf":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_file_type", "detail": "Only PDF files are accepted."},
        )

    # 2. Read + size check
    raw_bytes = await file.read()
    if len(raw_bytes) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error":  "file_too_large",
                "detail": f"File exceeds 50 MB limit ({len(raw_bytes) // (1024*1024)} MB received).",
            },
        )

    # 3. Save to disk
    paper_id = str(uuid.uuid4())
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    saved_path = UPLOAD_DIR / f"{paper_id}.pdf"
    saved_path.write_bytes(raw_bytes)

    # 4–7. Ingestion pipeline
    try:
        from app.services.parser import parse_pdf
        from app.services.chunker import chunk_from_sections, get_chunk_texts
        from app.services.embeddings import embed_chunks
        from app.db.sqlite import store_paper_metadata

        # Parse — returns title, text, pages, page_chunks, sections
        parsed = parse_pdf(str(saved_path))
        title: str = parsed.get("title") or (file.filename or "Untitled Paper")

        # Section-aware chunking — returns [{text, section, chunk_index}]
        chunks = chunk_from_sections(parsed["sections"])

        if not chunks:
            # Fallback: section detection failed, chunk raw text
            from app.services.chunker import chunk_text
            from app.services.embeddings import embed_chunks_plain
            plain_chunks = chunk_text(parsed["text"])
            embed_chunks_plain(paper_id=paper_id, chunks=plain_chunks)
            num_chunks = len(plain_chunks)
        else:
            # Embed with section metadata
            embed_chunks(paper_id=paper_id, chunks=chunks)
            num_chunks = len(chunks)

        # Store paper metadata in SQLite
        store_paper_metadata(
            paper_id=paper_id,
            title=title,
            num_chunks=num_chunks,
            file_path=str(saved_path),
        )

    except NotImplementedError:
        title = file.filename or "Untitled Paper"
        num_chunks = 0

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "parse_failed", "detail": f"Could not parse PDF: {exc}"},
        ) from exc

    return UploadResponse(
        paper_id=paper_id,
        title=title,
        num_chunks=num_chunks,
        status=PaperStatus.ready,
    )