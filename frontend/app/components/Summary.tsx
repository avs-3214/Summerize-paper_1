"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { SummarizeResponse } from "@/lib/types";

interface SummaryProps {
  summary: SummarizeResponse | null;
  loading: boolean;
  tierHint?: string;
}

export default function Summary({ summary, loading, tierHint }: SummaryProps) {
  if (loading) {
    return (
      <div className="w-full rounded-xl border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-950">
        <div className="flex items-center gap-3">
          <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-zinc-300 border-t-zinc-900 dark:border-zinc-700 dark:border-t-zinc-100" />
          <span className="text-sm text-zinc-600 dark:text-zinc-400">
            {tierHint === "expert"
              ? "Generating expert summary — this can take 10–15 seconds…"
              : "Generating summary…"}
          </span>
        </div>
        <div className="mt-6 space-y-2">
          <div className="h-3 w-3/4 animate-pulse rounded bg-zinc-200 dark:bg-zinc-800" />
          <div className="h-3 w-full animate-pulse rounded bg-zinc-200 dark:bg-zinc-800" />
          <div className="h-3 w-5/6 animate-pulse rounded bg-zinc-200 dark:bg-zinc-800" />
          <div className="h-3 w-2/3 animate-pulse rounded bg-zinc-200 dark:bg-zinc-800" />
        </div>
      </div>
    );
  }

  if (!summary) return null;

  return (
    <div className="w-full rounded-xl border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-950">
      <div className="mb-4 flex items-center justify-between">
        <span className="rounded-full bg-zinc-100 px-2.5 py-0.5 text-xs font-medium text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">
          {summary.tier}
        </span>
        {summary.from_cache && (
          <span className="rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs font-medium text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200">
            served from cache
          </span>
        )}
      </div>
      <article className="prose prose-zinc max-w-none dark:prose-invert">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>
          {summary.summary_markdown}
        </ReactMarkdown>
      </article>
    </div>
  );
}
