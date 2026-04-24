"use client";

import { useState } from "react";
import Upload from "./components/Upload";
import TierSelect from "./components/TierSelect";
import Summary from "./components/Summary";
import { generateSummary, parseApiError } from "@/lib/api";
import type { SummarizeResponse, Tier, UploadResponse } from "@/lib/types";

export default function Home() {
  const [paper, setPaper] = useState<UploadResponse | null>(null);
  const [tier, setTier] = useState<Tier>("intermediate");
  const [summary, setSummary] = useState<SummarizeResponse | null>(null);
  const [summarizing, setSummarizing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSummarize() {
    if (!paper) return;
    setError(null);
    setSummary(null);
    setSummarizing(true);
    try {
      const res = await generateSummary(paper.paper_id, tier);
      setSummary(res);
    } catch (err) {
      const apiErr = parseApiError(err);
      if (apiErr.retry_after) {
        setError(
          `Rate limited. Please retry in ${apiErr.retry_after} seconds.`
        );
      } else {
        setError(apiErr.detail);
      }
    } finally {
      setSummarizing(false);
    }
  }

  function handleReset() {
    setPaper(null);
    setSummary(null);
    setError(null);
    setTier("intermediate");
  }

  return (
    <div className="flex flex-1 flex-col items-center bg-zinc-50 px-4 py-12 dark:bg-black">
      <main className="flex w-full max-w-3xl flex-col gap-8">
        <header className="flex flex-col gap-2">
          <h1 className="text-3xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
            Paper Summarizer
          </h1>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            Upload a research paper and pick how deep you want the summary to
            go.
          </p>
        </header>

        <section className="flex flex-col gap-3">
          <Upload onUploaded={setPaper} disabled={!!paper} />
          {paper && (
            <div className="flex items-center justify-between rounded-md border border-zinc-200 bg-white px-3 py-2 text-sm dark:border-zinc-800 dark:bg-zinc-950">
              <div className="min-w-0">
                <div className="truncate font-medium text-zinc-900 dark:text-zinc-100">
                  {paper.title}
                </div>
                <div className="text-xs text-zinc-500 dark:text-zinc-400">
                  {paper.num_chunks} chunks · ready
                </div>
              </div>
              <button
                type="button"
                onClick={handleReset}
                className="ml-3 shrink-0 text-xs text-zinc-500 underline hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
              >
                upload another
              </button>
            </div>
          )}
        </section>

        {paper && (
          <section className="flex flex-col gap-4">
            <TierSelect
              value={tier}
              onChange={setTier}
              disabled={summarizing}
            />
            <button
              type="button"
              onClick={handleSummarize}
              disabled={summarizing}
              className="self-start rounded-full bg-zinc-900 px-5 py-2 text-sm font-medium text-zinc-50 transition-colors hover:bg-zinc-700 disabled:cursor-not-allowed disabled:opacity-60 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
            >
              {summarizing ? "Generating…" : "Generate summary"}
            </button>
          </section>
        )}

        {error && (
          <div
            role="alert"
            className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-200"
          >
            {error}
          </div>
        )}

        <Summary summary={summary} loading={summarizing} tierHint={tier} />
      </main>
    </div>
  );
}
