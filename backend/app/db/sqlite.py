"""
SQLAlchemy + SQLite setup.

Functions used by routes (stubs that work right now, P3 fills in real logic):
  - init_db()
  - store_paper_metadata()
  - get_paper()
  - get_cached_summary()
  - cache_summary()
"""

import os
from datetime import datetime, timezone
from sqlalchemy import create_engine, text, Column, String, Integer, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker

# ---------------------------------------------------------------------------
# Engine + session

SQLITE_DB = os.getenv("SQLITE_DB", "../data/sqlite/papers.db")

# ensure the directory exists
os.makedirs(os.path.dirname(os.path.abspath(SQLITE_DB)), exist_ok=True)

engine = create_engine(
    f"sqlite:///{SQLITE_DB}",
    connect_args={"check_same_thread": False},  # needed for SQLite + FastAPI
)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()


# ---------------------------------------------------------------------------
# Models

class Paper(Base):
    __tablename__ = "papers"

    paper_id  = Column(String, primary_key=True, index=True)
    title     = Column(String, nullable=False)
    num_chunks = Column(Integer, nullable=False)
    file_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Summary(Base):
    __tablename__ = "summaries"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    paper_id         = Column(String, index=True, nullable=False)
    tier             = Column(String, nullable=False)   # beginner | intermediate | expert
    summary_markdown = Column(Text, nullable=False)
    created_at       = Column(DateTime, default=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# init_db — called in main.py lifespan

def init_db():
    """Create all tables if they don't already exist."""
    Base.metadata.create_all(bind=engine)


# ---------------------------------------------------------------------------
# init_chroma shim — imported by main.py from db.chroma, but put a no-op
# here as a safety net in case db/chroma.py is also empty

# ---------------------------------------------------------------------------
# Paper CRUD

def store_paper_metadata(paper_id: str, title: str, num_chunks: int, file_path: str):
    with SessionLocal() as db:
        paper = Paper(
            paper_id=paper_id,
            title=title,
            num_chunks=num_chunks,
            file_path=file_path,
        )
        db.add(paper)
        db.commit()


def get_paper(paper_id: str) -> dict | None:
    with SessionLocal() as db:
        row = db.query(Paper).filter(Paper.paper_id == paper_id).first()
        if row is None:
            return None
        return {
            "paper_id": row.paper_id,
            "title": row.title,
            "num_chunks": row.num_chunks,
            "file_path": row.file_path,
            "created_at": row.created_at,
        }


# ---------------------------------------------------------------------------
# Summary cache CRUD

def get_cached_summary(paper_id: str, tier: str) -> dict | None:
    with SessionLocal() as db:
        row = (
            db.query(Summary)
            .filter(Summary.paper_id == paper_id, Summary.tier == tier)
            .first()
        )
        if row is None:
            return None
        return {
            "summary_markdown": row.summary_markdown,
            "created_at": row.created_at,
        }


def cache_summary(paper_id: str, tier: str, summary_markdown: str, created_at: datetime):
    with SessionLocal() as db:
        # upsert: delete existing then insert fresh
        db.query(Summary).filter(
            Summary.paper_id == paper_id, Summary.tier == tier
        ).delete()
        summary = Summary(
            paper_id=paper_id,
            tier=tier,
            summary_markdown=summary_markdown,
            created_at=created_at,
        )
        db.add(summary)
        db.commit()