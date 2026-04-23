# API Contracts

> **Source of truth for all frontend ↔ backend communication.**
> Every field name, type, and status code here is final for the hackathon.
> If you change anything, update this doc and notify the team.

---

## Base URL

| Environment | URL |
|-------------|-----|
| Local dev   | `http://localhost:8000` |
| Frontend env var | `NEXT_PUBLIC_API_URL` |

---

## Shared Conventions

- All request bodies are `application/json` unless noted.
- All successful responses return `Content-Type: application/json`.
- Timestamps are ISO 8601 strings (e.g. `"2024-01-15T10:30:00Z"`).
- `paper_id` is a UUID v4 string throughout.
- HTTP errors follow the shape: `{ "error": "<slug>", "detail": "<human message>" }`.

---

## Endpoints

### 1. `POST /upload`

Upload a PDF paper. Triggers parsing, chunking, and embedding. Returns as soon as the paper is ready to be summarized.

**Request**

```
Content-Type: multipart/form-data
```

| Field | Type   | Required | Description          |
|-------|--------|----------|----------------------|
| file  | File   | ✅        | PDF file to upload   |

**Response 200 — OK**

```json
{
  "paper_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "title": "Attention Is All You Need",
  "num_chunks": 42,
  "status": "ready"
}
```

| Field       | Type   | Description                                      |
|-------------|--------|--------------------------------------------------|
| paper_id    | string | UUID for this paper, used in all future requests |
| title       | string | Extracted from PDF metadata or first heading     |
| num_chunks  | int    | Number of text chunks stored in ChromaDB         |
| status      | string | Always `"ready"` on success                      |

**Error Responses**

| Code | `error` slug        | Meaning                              |
|------|---------------------|--------------------------------------|
| 400  | `invalid_file_type` | Uploaded file is not a PDF           |
| 400  | `file_too_large`    | File exceeds 50 MB limit             |
| 422  | `parse_failed`      | PyMuPDF4LLM could not extract text   |
| 500  | `internal_error`    | Unexpected server error              |

---

### 2. `POST /summarize`

Generate (or retrieve from cache) a summary at the requested tier.

**Request**

```json
{
  "paper_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "tier": "intermediate"
}
```

| Field    | Type   | Required | Values                                  |
|----------|--------|----------|-----------------------------------------|
| paper_id | string | ✅        | UUID returned from `/upload`            |
| tier     | string | ✅        | `"beginner"` \| `"intermediate"` \| `"expert"` |

**Response 200 — OK**

```json
{
  "paper_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "tier": "intermediate",
  "summary_markdown": "## Summary\n\nThis paper introduces...",
  "from_cache": false,
  "created_at": "2024-01-15T10:30:00Z"
}
```

| Field            | Type    | Description                                            |
|------------------|---------|--------------------------------------------------------|
| paper_id         | string  | Echoes back the requested paper_id                     |
| tier             | string  | Echoes back the requested tier                         |
| summary_markdown | string  | Full summary as a Markdown string (render with react-markdown) |
| from_cache       | boolean | `true` if result was served from SQLite cache          |
| created_at       | string  | ISO 8601 timestamp of when this summary was generated  |

**Error Responses**

| Code | `error` slug      | Extra fields          | Meaning                                  |
|------|-------------------|-----------------------|------------------------------------------|
| 404  | `paper_not_found` | —                     | `paper_id` not in SQLite                 |
| 422  | `invalid_tier`    | —                     | `tier` is not one of the three values    |
| 429  | `rate_limited`    | `retry_after: int`    | Groq rate limit hit; retry after N secs  |
| 500  | `llm_error`       | —                     | Groq call failed after retries           |
| 500  | `internal_error`  | —                     | Unexpected server error                  |

**Rate limit response shape:**

```json
{
  "error": "rate_limited",
  "detail": "Groq rate limit hit. Please retry.",
  "retry_after": 30
}
```

---

### 3. `GET /summarize/{paper_id}?tier=intermediate`

Retrieve a previously generated summary from cache. Does **not** call Groq — returns 404 if no cached summary exists for this paper+tier combination.

**Path Parameter**

| Parameter | Type   | Description         |
|-----------|--------|---------------------|
| paper_id  | string | UUID of the paper   |

**Query Parameter**

| Parameter | Type   | Required | Values                                           |
|-----------|--------|----------|--------------------------------------------------|
| tier      | string | ✅        | `"beginner"` \| `"intermediate"` \| `"expert"` |

**Response 200 — OK**

Same shape as `POST /summarize` response, always with `"from_cache": true`.

```json
{
  "paper_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "tier": "intermediate",
  "summary_markdown": "## Summary\n\nThis paper introduces...",
  "from_cache": true,
  "created_at": "2024-01-15T10:30:00Z"
}
```

**Error Responses**

| Code | `error` slug        | Meaning                                         |
|------|---------------------|-------------------------------------------------|
| 404  | `paper_not_found`   | `paper_id` not in SQLite                        |
| 404  | `summary_not_found` | Paper exists but no cached summary for this tier |
| 422  | `invalid_tier`      | `tier` query param is not one of the three values |

---

## Tier Behaviour Reference

| Tier         | Model                   | Chunks Retrieved          | Target Length | Style                                            |
|--------------|-------------------------|---------------------------|---------------|--------------------------------------------------|
| beginner     | llama-3.1-8b-instant    | Top 3 + abstract          | ~250 words    | Plain language, no jargon, ELI-undergrad         |
| intermediate | llama-3.3-70b-versatile | Top 6–8 + section headers | ~600 words    | Structured: contributions, methodology, findings |
| expert       | llama-3.3-70b-versatile | Section-by-section (map-reduce) | ~1500 words | Technical deep-dive, limitations, future work |

---

## Frontend Integration Notes (for P4)

```typescript
// lib/api.ts — base axios instance
import axios from 'axios';

const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL,
});

// Upload
const upload = (file: File) => {
  const form = new FormData();
  form.append('file', file);
  return api.post<UploadResponse>('/upload', form);
};

// Summarize
const summarize = (paperId: string, tier: Tier) =>
  api.post<SummarizeResponse>('/summarize', { paper_id: paperId, tier });

// Get cached
const getSummary = (paperId: string, tier: Tier) =>
  api.get<SummarizeResponse>(`/summarize/${paperId}`, { params: { tier } });
```

**TypeScript types** (add to `lib/types.ts`):

```typescript
export type Tier = 'beginner' | 'intermediate' | 'expert';

export interface UploadResponse {
  paper_id: string;
  title: string;
  num_chunks: number;
  status: 'ready';
}

export interface SummarizeResponse {
  paper_id: string;
  tier: Tier;
  summary_markdown: string;
  from_cache: boolean;
  created_at: string;
}

export interface ApiError {
  error: string;
  detail: string;
  retry_after?: number;
}
```

---

## Backend Integration Notes

- `POST /upload` should return **after** all chunks are embedded — the frontend polls nothing, it's synchronous.
- `POST /summarize` checks SQLite cache **before** calling Groq. If `from_cache: true`, Groq is never called.
- `GET /summarize/{id}` is cache-only — never triggers generation.
- Expert tier uses map-reduce: summarize each section chunk independently, then synthesize. This can take 10–15s — the frontend loading state must handle this gracefully.
- All Groq calls should be wrapped in `tenacity` retry logic (3 retries, exponential backoff) before surfacing a 429 or 500.
