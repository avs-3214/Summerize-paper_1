// TypeScript types — mirror of backend/app/models/schema.py
// If contracts change, update both files.

export type Tier = "beginner" | "intermediate" | "expert";

export interface UploadResponse {
  paper_id: string;
  title: string;
  num_chunks: number;
  status: "ready";
}

export interface SummarizeResponse {
  paper_id: string;
  tier: Tier;
  summary_markdown: string;
  from_cache: boolean;
  created_at: string; // ISO 8601 UTC string
}

export interface ApiError {
  error: string;   // machine-readable slug
  detail: string;  // human-readable message
  retry_after?: number; // only on 429 responses
}