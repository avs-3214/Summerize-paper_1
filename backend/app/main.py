"""
FastAPI application entry point.

Run from inside backend/ with:
    uvicorn app.main:app --reload
"""

from contextlib import asynccontextmanager

# Load .env into os.environ FIRST — before any service module reads os.getenv()
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.routes import upload, summarize, history, query


class Settings(BaseSettings):
    groq_api_key: str
    model_beginner: str = "llama-3.1-8b-instant"
    model_advanced: str = "llama-3.3-70b-versatile"
    chroma_dir: str = "../data/chroma"
    sqlite_db: str = "../data/sqlite/papers.db"
    allowed_origins: str = "http://localhost:3000"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.db.sqlite import init_db
    from app.db.chroma import init_chroma

    print("🚀 Starting up Paper Summarizer API...")
    init_db()
    init_chroma()
    print("✅ DB ready.")

    yield

    print("🛑 Shutting down...")


app = FastAPI(
    title="Paper Summarizer API",
    description=(
        "Ingest academic PDFs and generate beginner / intermediate / expert "
        "summaries via Groq (Llama 3.1 8B + Llama 3.3 70B)."
    ),
    version="0.3.0",
    lifespan=lifespan,
)

origins = [o.strip() for o in settings.allowed_origins.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload.router,    tags=["upload"])
app.include_router(summarize.router, tags=["summarize"])
app.include_router(history.router,   tags=["history"])
app.include_router(query.router,     tags=["query"])


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok", "version": app.version}