"use client";

import { useRef, useState } from "react";
import { uploadPaper, parseApiError } from "@/lib/api";
import type { UploadResponse } from "@/lib/types";

interface UploadProps {
  onUploaded: (paper: UploadResponse) => void;
  disabled?: boolean;
}

export default function Upload({ onUploaded, disabled }: UploadProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filename, setFilename] = useState<string | null>(null);

  async function handleFile(file: File) {
    setError(null);
    setFilename(file.name);

    if (file.type !== "application/pdf") {
      setError("Only PDF files are accepted.");
      return;
    }

    setLoading(true);
    try {
      const paper = await uploadPaper(file);
      onUploaded(paper);
    } catch (err) {
      const apiErr = parseApiError(err);
      setError(apiErr.detail);
    } finally {
      setLoading(false);
    }
  }

  function onDrop(e: React.DragEvent<HTMLLabelElement>) {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) handleFile(file);
  }

  const isDisabled = disabled || loading;

  return (
    <div className="w-full">
      <label
        htmlFor="pdf-upload"
        onDragOver={(e) => {
          e.preventDefault();
          if (!isDisabled) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={[
          "flex flex-col items-center justify-center w-full rounded-xl border-2 border-dashed px-6 py-12 text-center transition-colors",
          isDisabled ? "cursor-not-allowed opacity-60" : "cursor-pointer",
          dragging
            ? "border-zinc-900 bg-zinc-100 dark:border-zinc-100 dark:bg-zinc-900"
            : "border-zinc-300 bg-white hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-950 dark:hover:bg-zinc-900",
        ].join(" ")}
      >
        <svg
          className="mb-3 h-10 w-10 text-zinc-400"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.5}
          viewBox="0 0 24 24"
          aria-hidden="true"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M12 16.5V9m0 0l-3 3m3-3l3 3M4.5 16.5v1.125A2.375 2.375 0 006.875 20h10.25A2.375 2.375 0 0019.5 17.625V16.5"
          />
        </svg>
        <div className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
          {loading ? "Uploading…" : "Drop a PDF here or click to browse"}
        </div>
        <div className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
          PDF only · 50 MB max
        </div>
        {filename && !error && (
          <div className="mt-3 text-xs text-zinc-600 dark:text-zinc-300">
            {filename}
          </div>
        )}
        <input
          ref={inputRef}
          id="pdf-upload"
          type="file"
          accept="application/pdf"
          disabled={isDisabled}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) handleFile(file);
          }}
          className="sr-only"
        />
      </label>

      {error && (
        <div
          role="alert"
          className="mt-3 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-200"
        >
          {error}
        </div>
      )}
    </div>
  );
}
