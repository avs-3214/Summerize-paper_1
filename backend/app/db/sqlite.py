"""
SQLAlchemy + SQLite setup.
"""

import hashlib
import os
from datetime import datetime, timezone
from sqlalchemy import create_engine, Column, String, Integer, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker

# ---------------------------------------------------------------------------
# Engine + session

SQLITE_DB = os.getenv("SQLITE_DB", "../data/sqlite/papers.db")
os.makedirs(os.path.dirname(os.path.abspath(SQLITE_DB)), exist_ok=True)

engine = create_engine(
    f"sqlite:///{SQLITE_DB}",
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()


# ---------------------------------------------------------------------------
# ORM Models

class Paper(Base):
    __tablename__ = "papers"
    paper_id   = Column(String, primary_key=True, index=True)
    title      = Column(String, nullable=False)
    num_chunks = Column(Integer, nullable=False)
    file_path  = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Summary(Base):
    __tablename__ = "summaries"
    id               = Column(Integer, primary_key=True, autoincrement=True)
    paper_id         = Column(String, index=True, nullable=False)
    tier             = Column(String, nullable=False)
    summary_markdown = Column(Text, nullable=False)
    created_at       = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class QueryCache(Base):
    """
    Caches query answers keyed by (paper_id, question_hash, tier).
    question_hash = sha256(question.strip().lower() + tier) — keeps the key
    short and consistent regardless of whitespace variations.
    """
    __tablename__ = "query_cache"
    id              = Column(Integer, primary_key=True, autoincrement=True)
    paper_id        = Column(String, index=True, nullable=False)
    question_hash   = Column(String, nullable=False)   # sha256 hex
    question        = Column(Text, nullable=False)     # original text for display
    tier            = Column(String, nullable=False)
    answer_markdown = Column(Text, nullable=False)
    created_at      = Column(DateTime, default=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# init_db

def init_db():
    """Create all tables if they don't already exist."""
    Base.metadata.create_all(bind=engine)


# ---------------------------------------------------------------------------
# Paper CRUD

def store_paper_metadata(paper_id: str, title: str, num_chunks: int, file_path: str):
    with SessionLocal() as db:
        paper = Paper(paper_id=paper_id, title=title,
                      num_chunks=num_chunks, file_path=file_path)
        db.add(paper)
        db.commit()


def get_paper(paper_id: str) -> dict | None:
    with SessionLocal() as db:
        row = db.query(Paper).filter(Paper.paper_id == paper_id).first()
        if row is None:
            return None
        return {
            "paper_id":   row.paper_id,
            "title":      row.title,
            "num_chunks": row.num_chunks,
            "file_path":  row.file_path,
            "created_at": row.created_at,
        }


# ---------------------------------------------------------------------------
# Summary cache CRUD

def get_cached_summary(paper_id: str, tier: str) -> dict | None:
    with SessionLocal() as db:
        row = (db.query(Summary)
               .filter(Summary.paper_id == paper_id, Summary.tier == tier)
               .first())
        if row is None:
            return None
        return {"summary_markdown": row.summary_markdown, "created_at": row.created_at}


def cache_summary(paper_id: str, tier: str, summary_markdown: str, created_at: datetime):
    with SessionLocal() as db:
        db.query(Summary).filter(
            Summary.paper_id == paper_id, Summary.tier == tier
        ).delete()
        db.add(Summary(paper_id=paper_id, tier=tier,
                       summary_markdown=summary_markdown, created_at=created_at))
        db.commit()


# ---------------------------------------------------------------------------
# Query cache CRUD

def _question_hash(question: str, tier: str) -> str:
    raw = (question.strip().lower() + "|" + tier).encode()
    return hashlib.sha256(raw).hexdigest()


def get_cached_query(paper_id: str, question: str, tier: str) -> dict | None:
    qhash = _question_hash(question, tier)
    with SessionLocal() as db:
        row = (db.query(QueryCache)
               .filter(QueryCache.paper_id == paper_id,
                       QueryCache.question_hash == qhash,
                       QueryCache.tier == tier)
               .first())
        if row is None:
            return None
        return {"answer_markdown": row.answer_markdown, "created_at": row.created_at}


def cache_query_result(paper_id: str, question: str, tier: str,
                       answer_markdown: str, created_at: datetime):
    qhash = _question_hash(question, tier)
    with SessionLocal() as db:
        db.query(QueryCache).filter(
            QueryCache.paper_id == paper_id,
            QueryCache.question_hash == qhash,
            QueryCache.tier == tier,
        ).delete()
        db.add(QueryCache(
            paper_id=paper_id,
            question_hash=qhash,
            question=question,
            tier=tier,
            answer_markdown=answer_markdown,
            created_at=created_at,
        ))
        db.commit()


# ---------------------------------------------------------------------------
# History query

def get_recent_papers(limit: int = 10) -> list[dict]:
    """
    Return the last `limit` uploaded papers, each with any cached summaries.
    """
    with SessionLocal() as db:
        papers = (db.query(Paper)
                  .order_by(Paper.created_at.desc())
                  .limit(limit)
                  .all())
        result = []
        for paper in papers:
            summary_rows = (db.query(Summary)
                            .filter(Summary.paper_id == paper.paper_id)
                            .all())
            summaries = {"beginner": None, "intermediate": None, "expert": None}
            for s in summary_rows:
                if s.tier in summaries:
                    summaries[s.tier] = s.summary_markdown
            result.append({
                "paper_id":    paper.paper_id,
                "title":       paper.title,
                "num_chunks":  paper.num_chunks,
                "uploaded_at": paper.created_at,
                "summaries":   summaries,
            })
        return result