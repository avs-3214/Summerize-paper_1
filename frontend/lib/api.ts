// Axios wrapper — one function per API contract endpoint.
// Import these in components; don't call axios directly.

import axios, { AxiosError } from "axios";
import type { Tier, UploadResponse, SummarizeResponse, ApiError } from "./types";

// ---------------------------------------------------------------------------
// Base instance

const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL,
  headers: { "Content-Type": "application/json" },
});

// ---------------------------------------------------------------------------
// Error helper

/**
 * Extracts a typed ApiError from an AxiosError.
 * Falls back to a generic message if the response body isn't our standard shape.
 */
export function parseApiError(err: unknown): ApiError {
  if (axios.isAxiosError(err)) {
    const axiosErr = err as AxiosError<ApiError>;
    if (axiosErr.response?.data?.error) {
      return axiosErr.response.data;
    }
    return {
      error: "network_error",
      detail: axiosErr.message ?? "Network error — is the backend running?",
    };
  }
  return { error: "unknown_error", detail: String(err) };
}

// ---------------------------------------------------------------------------
// POST /upload

/**
 * Upload a PDF paper.
 * Returns UploadResponse with a paper_id to use in summarize calls.
 *
 * @throws ApiError on 400 (invalid_file_type, file_too_large), 422, 500
 */
export async function uploadPaper(file: File): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);

  const { data } = await api.post<UploadResponse>("/upload", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });

  return data;
}

// ---------------------------------------------------------------------------
// POST /summarize

/**
 * Generate (or serve from cache) a tiered summary.
 *
 * - Returns immediately if a cached summary exists (data.from_cache === true).
 * - Calls Groq otherwise — expert tier can take 10–15 seconds.
 * - On 429, the error includes retry_after (seconds). Show a countdown.
 *
 * @throws ApiError on 404, 429, 500
 */
export async function generateSummary(
  paperId: string,
  tier: Tier
): Promise<SummarizeResponse> {
  const { data } = await api.post<SummarizeResponse>("/summarize", {
    paper_id: paperId,
    tier,
  });
  return data;
}

// ---------------------------------------------------------------------------
// GET /summarize/{paper_id}?tier=...

/**
 * Retrieve a previously generated summary from cache.
 * Never calls Groq — 404 if not cached yet.
 *
 * @throws ApiError on 404 (paper_not_found | summary_not_found)
 */
export async function getCachedSummary(
  paperId: string,
  tier: Tier
): Promise<SummarizeResponse> {
  const { data } = await api.get<SummarizeResponse>(`/summarize/${paperId}`, {
    params: { tier },
  });
  return data;
}

// ---------------------------------------------------------------------------
// Health check (useful for debug / startup verification)

export async function healthCheck(): Promise<{ status: string }> {
  const { data } = await api.get<{ status: string }>("/health");
  return data;
}