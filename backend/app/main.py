"""
app/main.py
FastAPI application entry point.

Run from inside backend/ with:
    uvicorn app.main:app --reload

Must be run from inside backend/ so that load_dotenv() finds .env correctly.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic_settings import BaseSettings

from app.routes import upload, summarize


# ---------------------------------------------------------------------------
# Settings — loaded from backend/.env via pydantic-settings

class Settings(BaseSettings):
    groq_api_key: str
    model_beginner: str = "llama-3.1-8b-instant"
    model_advanced: str = "llama-3.3-70b-versatile"
    chroma_dir: str = "../data/chroma"
    sqlite_db: str = "../data/sqlite/papers.db"

    # CORS — comma-separated list of allowed origins
    # In dev this is just the Next.js dev server.
    allowed_origins: str = "http://localhost:3000"

    class Config:
        env_file = ".env"          # relative to CWD, so run from backend/
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()


# ---------------------------------------------------------------------------
# Lifespan — startup / shutdown hooks

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Runs once on startup (before first request) and once on shutdown.
    Use for DB initialisation, model warm-up, etc.
    """
    # Import here to avoid circular imports at module load time
    from app.db.sqlite import init_db
    from app.db.chroma import init_chroma

    print("🚀 Starting up Paper Summarizer API...")
    init_db()       # creates tables if they don't exist
    init_chroma()   # creates collection if it doesn't exist
    print("✅ DB ready.")

    yield  # application runs here

    print("🛑 Shutting down...")


# ---------------------------------------------------------------------------
# App

app = FastAPI(
    title="Paper Summarizer API",
    description=(
        "Ingest academic PDFs and generate beginner / intermediate / expert "
        "summaries via Groq (Llama 3.1 8B + Llama 3.3 70B)."
    ),
    version="0.1.0",
    lifespan=lifespan,
    # Expose Swagger at /docs and ReDoc at /redoc (default FastAPI behaviour)
)


# ---------------------------------------------------------------------------
# CORS - Allows the Next.js dev server (localhost:3000) to call this API.

origins = [o.strip() for o in settings.allowed_origins.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Routers

app.include_router(upload.router, tags=["upload"])
app.include_router(summarize.router, tags=["summarize"])


# ---------------------------------------------------------------------------
# Health check
# Useful for smoke-testing before the real routes are wired up.

@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok", "version": app.version}