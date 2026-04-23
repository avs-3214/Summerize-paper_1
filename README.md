# Paper Summarizer

A local-first tool that ingests academic research papers (PDF) and generates **context-aware summaries** tailored to the reader's expertise level — beginner, intermediate, or expert.

Upload a paper, pick your tier, get a summary that actually fits how much you want to know.

---

## What It Does

- Accepts research papers as PDF uploads
- Parses the paper, breaks it into semantically meaningful chunks, and embeds them into a vector database
- Generates a summary at one of three depth levels, each using a different model, prompt style, and retrieval strategy
- Caches generated summaries so repeat requests are instant
- Runs entirely on your laptop — the only external call is to the Groq API for LLM inference

## Tier System

| Tier | Model | Chunks Used | Output Style |
|------|-------|-------------|--------------|
| **Beginner** | Llama 3.1 8B Instant | Top 3 + abstract | Plain-language overview, ~250 words, why it matters |
| **Intermediate** | Llama 3.3 70B Versatile | Top 6–8 + section headers | Structured summary with contributions, methodology, findings, ~600 words |
| **Expert** | Llama 3.3 70B Versatile | Section-by-section, map-reduce | Technical deep-dive with limitations, comparisons, ~1500 words |

The ingestion pipeline is identical for all three — only the generation step changes. This keeps the system simple while still producing meaningfully different outputs per tier.

---

## Tech Stack

| Layer | Tool |
|-------|------|
| Frontend | Next.js 14 (App Router, TypeScript, Tailwind CSS) |
| Backend | FastAPI (Python 3.11+) |
| PDF Parsing | PyMuPDF4LLM |
| Embeddings | sentence-transformers (`bge-small-en-v1.5`) |
| Vector DB | ChromaDB (embedded mode) |
| Metadata DB | SQLite |
| LLM Inference | Groq API (Llama 3.1 8B + Llama 3.3 70B) |
| Version Control | Git + GitHub (feature branches per team member) |

---

## How It Works (End-to-End Flow)

```
User uploads PDF
      │
      ▼
Frontend (Next.js) ─────── POST /upload ───────▶ Backend (FastAPI)
                                                      │
                                                      ▼
                                         PDF parsed with PyMuPDF4LLM
                                                      │
                                                      ▼
                                         Text chunked into ~500-token pieces
                                                      │
                                                      ▼
                                         Chunks embedded with sentence-transformers
                                                      │
                                                      ▼
                                         Stored in ChromaDB + metadata in SQLite
                                                      │
                                                      ▼
User picks tier (beginner/intermediate/expert)
      │
      ▼
Frontend ─────── POST /summarize ───────────▶ Backend
                                                      │
                                                      ▼
                                         Check SQLite cache
                                                      │
                                  (miss)              ▼
                                         Retrieve relevant chunks from ChromaDB
                                                      │
                                                      ▼
                                         Call Groq with tier-specific prompt + model
                                                      │
                                                      ▼
                                         Cache result in SQLite
                                                      │
                                                      ▼
                        Summary (markdown) returned to frontend
                                                      │
                                                      ▼
                        Rendered with react-markdown
```

---

## Project Structure

```
paper-summarizer/
│
├── README.md                          # You are here
├── .gitignore                         # Ignores .env, venv, node_modules, data/*
│
├── backend/                           # Python / FastAPI side
│   ├── .env                           # Real Groq key (gitignored)
│   ├── .env.example                   # Template for teammates
│   ├── requirements.txt               # Pinned Python dependencies
│   │
│   └── app/
│       ├── __init__.py
│       ├── main.py                    # FastAPI entrypoint, CORS, router mounts
│       │
│       ├── routes/                    # HTTP endpoint definitions (thin layer)
│       │   ├── __init__.py
│       │   ├── upload.py              # POST /upload — accepts PDF, triggers ingestion
│       │   └── summarize.py           # POST /summarize — generates tier-specific summary
│       │
│       ├── services/                  # Business logic (pipeline steps)
│       │   ├── __init__.py
│       │   ├── parser.py              # PDF → clean markdown text (PyMuPDF4LLM)
│       │   ├── chunker.py             # Text → overlapping chunks
│       │   ├── embeddings.py          # Chunks → vectors (sentence-transformers)
│       │   ├── retriever.py           # Given paper_id + tier, return relevant chunks
│       │   └── llm.py                 # Groq API wrapper with tier-specific prompts
│       │
│       ├── db/                        # Database connections
│       │   ├── __init__.py
│       │   ├── sqlite.py              # SQLite engine + session for metadata/cache
│       │   └── chroma.py              # ChromaDB embedded client
│       │
│       └── models/                    # Pydantic request/response schemas
│           ├── __init__.py
│           └── schema.py              # PaperUpload, SummaryRequest, SummaryResponse
│
├── frontend/                          # Next.js side (no src/ — app/ at root)
│   ├── README.md                      # Default Next.js readme
│   ├── .env.local                     # Local env (gitignored)
│   ├── .env.example                   # Template
│   ├── package.json
│   ├── package-lock.json
│   ├── tsconfig.json
│   ├── next.config.ts
│   ├── next-env.d.ts
│   ├── eslint.config.mjs
│   ├── postcss.config.mjs
│   │
│   ├── app/                           # App Router root
│   │   ├── layout.tsx                 # Root layout
│   │   ├── page.tsx                   # Main page — upload + tier select + summary
│   │   ├── globals.css                # Tailwind base styles
│   │   ├── favicon.ico
│   │   └── components/                # (to be created) UI pieces
│   │       ├── Upload.tsx             # File drop zone, POSTs to /upload
│   │       ├── TierSelect.tsx         # 3-way toggle for tier
│   │       └── Summary.tsx            # Renders returned markdown
│   │
│   ├── lib/                           # (to be created) client-side helpers
│   │   └── api.ts                     # axios wrapper — uploadPaper, getSummary
│   │
│   └── public/                        # Static assets (icons, favicon)
│       ├── file.svg
│       ├── globe.svg
│       ├── next.svg
│       ├── vercel.svg
│       └── window.svg
│
└── data/                              # Local data (contents gitignored)
    ├── chroma/                        # ChromaDB persistence folder (empty on clone)
    ├── sqlite/                        # SQLite metadata DB
    │   └── papers.db                  # Created on first backend run
    └── uploads/                       # Raw uploaded PDFs (empty on clone)
```

> **A note on `data/` folders:** `chroma/`, `sqlite/`, and `uploads/` start empty. Git won't track empty folders on its own, so they may contain a `.gitkeep` placeholder so the structure survives a fresh clone. `papers.db` inside `data/sqlite/` is created automatically on first run and is gitignored.

### What Lives Where (Plain English)

- **`backend/app/routes/`** — Just the HTTP endpoints. Validates input, calls a service, returns the response. No logic.
- **`backend/app/services/`** — All the actual pipeline work. Each file is one step in the flow above. If a teammate is debugging chunking, they open `chunker.py`. If it's an LLM issue, `llm.py`. No hunting.
- **`backend/app/db/`** — One file per database. `sqlite.py` handles papers + cached summaries. `chroma.py` handles vectors.
- **`backend/app/models/`** — Pydantic schemas that define what JSON shapes the API accepts and returns. The frontend TypeScript types should mirror these.
- **`frontend/app/`** — Next.js 14 App Router pages and components. Server-render by default; add `"use client"` only where interactivity is needed.
- **`frontend/lib/api.ts`** — One axios instance, typed functions for each backend endpoint. Everything hitting the backend goes through here.
- **`data/`** — Everything written at runtime. Contents are never committed; only the folder structure is tracked.

---

## Quick Start

### Prerequisites
- Python 3.11+
- Node.js 20+
- A Groq API key (free tier) from [console.groq.com](https://console.groq.com)

### First-Time Setup (each teammate)

```bash
# Clone
git clone <repo-url>
cd paper-summarizer

# Backend
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env       # then edit .env and paste your Groq key
cd ..

# Frontend
cd frontend
npm install
cp .env.example .env.local
cd ..
```

### Running Locally

Open two terminals.

**Terminal 1 — backend:**
```bash
cd backend
source venv/bin/activate
uvicorn app.main:app --reload
```
Backend runs at [http://localhost:8000](http://localhost:8000). Swagger docs at [/docs](http://localhost:8000/docs).

**Terminal 2 — frontend:**
```bash
cd frontend
npm run dev
```
Frontend runs at [http://localhost:3000](http://localhost:3000).

> **Important:** always run backend commands from inside the `backend/` folder so `.env` loads correctly.

---

## Git Workflow

- `main` is protected — merge only via PR with 1 approval
- Each person works on their feature branch: `feat/p1-ingestion`, `feat/p2-summaries`, etc.
- Pull from `main` daily, commit often, push at the end of each work session
- Commit messages: `feat(scope): description`, `fix(scope): description`, `docs(scope): description`
- Never commit `.env`, `venv/`, `node_modules/`, or files inside `data/`

---

## Known Issues

- **Groq rate limits** hit fast on the free tier. Use Llama 3.1 8B during testing; save 70B for final runs.
- **PyMuPDF4LLM isn't perfect** on multi-column layouts with lots of equations — output may need cleanup.
- **Long papers exceed context windows.** Expert tier uses map-reduce to summarize section-by-section, then synthesize.
- **Pre-cache demo papers.** A 20-second spinner during a live demo looks bad. Run the pipeline once before showing it off.
- **`.env` loading is path-sensitive.** Run backend commands from inside `backend/`, not from the project root.

---

## API Summary

### `POST /upload`
Accepts multipart/form-data with a PDF file. Returns a `paper_id`.

### `POST /summarize`
Body: `{ "paper_id": "...", "tier": "beginner" | "intermediate" | "expert" }`. Returns markdown summary.

### `GET /summarize/{paper_id}?tier=...`
Retrieves a cached summary if available.