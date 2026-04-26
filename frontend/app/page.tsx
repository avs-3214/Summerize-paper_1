"use client";

import { useState, useRef, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

// ── Google Fonts ──────────────────────────────────────────────────────────────
const injectFonts = () => {
  if (document.getElementById("vectara-fonts")) return;
  const link = document.createElement("link");
  link.id = "vectara-fonts";
  link.rel = "stylesheet";
  link.href =
    "https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&family=Instrument+Serif:ital@0;1&display=swap";
  document.head.appendChild(link);
};

// ── API ───────────────────────────────────────────────────────────────────────
const API_BASE = "http://localhost:8000";

function parseApiError(err) {
  if (err?.response) {
    const d = err.response.data || {};
    return {
      error: d.error || "api_error",
      detail: d.detail || `Server error (${err.response.status})`,
      retry_after: d.retry_after ?? null,
    };
  }
  return { error: "network_error", detail: "Cannot reach the server. Is it running?", retry_after: null };
}

// Step 1 — POST /upload  (multipart/form-data)
// Returns: { paper_id, title, num_chunks, status }
async function apiUpload(file) {
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch(`${API_BASE}/upload`, { method: "POST", body: fd });
  if (!res.ok) throw { response: { status: res.status, data: await res.json().catch(() => ({})) } };
  return res.json();
}

// Step 2a — GET /summarize/{paper_id}?tier=…  (cache check — never triggers LLM)
// Returns: SummarizeResponse  or  404 if not cached
async function apiGetCached(paperId, tier) {
  const res = await fetch(`${API_BASE}/summarize/${paperId}?tier=${tier}`);
  if (!res.ok) throw { response: { status: res.status, data: await res.json().catch(() => ({})) } };
  return res.json();
}

// Step 2b — POST /summarize  (generate — may take 10–15 s for expert tier)
// Body: { paper_id, tier }
// Returns: { paper_id, tier, summary_markdown, from_cache, created_at }
async function apiGenerate(paperId, tier) {
  const res = await fetch(`${API_BASE}/summarize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ paper_id: paperId, tier }),
  });
  if (!res.ok) throw { response: { status: res.status, data: await res.json().catch(() => ({})) } };
  return res.json();
}

// Step 3 — GET /history  (last 5 uploaded papers with cached summaries)
// Returns: { papers: [{ paper_id, title, num_chunks, uploaded_at, summaries }] }
async function apiHistory() {
  const res = await fetch(`${API_BASE}/history?limit=10`);
  if (!res.ok) return { papers: [] };  // fail silently — history is non-critical
  return res.json();
}

// ── Tiers ─────────────────────────────────────────────────────────────────────
const TIERS = [
  { id: "beginner",     label: "Beginner",     dot: "#2d7a4f", desc: "Plain-language overview" },
  { id: "intermediate", label: "Intermediate", dot: "#b87333", desc: "Balanced depth & key insights" },
  { id: "expert",       label: "Expert",       dot: "#b04a2a", desc: "Full technical detail" },
];

// ── Small components ──────────────────────────────────────────────────────────
function Toast({ msg, type, visible }) {
  return (
    <div style={{
      position: "fixed", bottom: 24, right: 24, zIndex: 999,
      background: "#e4dfd2",
      border: `1px solid ${type === "error" ? "rgba(176,74,42,.4)" : "rgba(45,122,79,.35)"}`,
      borderRadius: 12, padding: "12px 18px", fontSize: 13,
      color: type === "error" ? "#b04a2a" : "#2d7a4f",
      transform: visible ? "none" : "translateY(60px)",
      opacity: visible ? 1 : 0, transition: "all .3s",
      pointerEvents: "none", maxWidth: 360, fontFamily: "JetBrains Mono, monospace",
    }}>{msg}</div>
  );
}

function RateLimitBanner({ retryAfter, onDismiss }) {
  const [n, setN] = useState(retryAfter);
  useEffect(() => {
    if (n <= 0) { onDismiss?.(); return; }
    const t = setTimeout(() => setN(x => x - 1), 1000);
    return () => clearTimeout(t);
  }, [n, onDismiss]);
  if (n <= 0) return null;
  return (
    <div style={{
      background: "rgba(184,115,51,.08)", border: "1px solid rgba(251,191,36,.3)",
      borderRadius: 10, padding: "10px 14px", fontSize: 12, color: "#b87333",
      fontFamily: "JetBrains Mono, monospace", display: "flex", alignItems: "center", gap: 8, marginBottom: 12,
    }}>
      ⏳ Rate limited — retry in <strong>{n}s</strong>
    </div>
  );
}

function Spinner() {
  return (
    <div style={{
      width: 16, height: 16, borderRadius: "50%",
      border: "2px solid rgba(255,255,255,.12)", borderTopColor: "#8b5e2a",
      animation: "spin .7s linear infinite", flexShrink: 0,
    }} />
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────
export default function Vectara() {
  useEffect(() => { injectFonts(); }, []);

  // ── Seed history from backend on mount ──────────────────────────────────────
  useEffect(() => {
    apiHistory().then(({ papers }) => {
      if (!papers?.length) return;
      // Normalise backend shape → same shape as in-session entries
      // Backend: { paper_id, title, num_chunks, uploaded_at, summaries: { beginner, intermediate, expert } }
      // In-session: { doc: { paper_id, title, num_chunks }, tier, summary: { summary_markdown, from_cache, created_at } }
      const entries = papers.flatMap(p => {
        // For each paper, create one entry per tier that has a cached summary
        const tiers = ["beginner", "intermediate", "expert"];
        const found = tiers
          .filter(t => p.summaries[t] !== null)
          .map(t => ({
            doc:     { paper_id: p.paper_id, title: p.title, num_chunks: p.num_chunks },
            tier:    t,
            summary: {
              summary_markdown: p.summaries[t],
              from_cache:       true,
              created_at:       p.uploaded_at,
            },
            fromBackend: true,
          }));
        // If no summaries yet, still show the paper so user can generate one
        if (found.length === 0) {
          return [{
            doc:     { paper_id: p.paper_id, title: p.title, num_chunks: p.num_chunks },
            tier:    null,
            summary: null,
            fromBackend: true,
          }];
        }
        return found;
      });
      setHistory(entries.slice(0, 10));
    });
  }, []);

  // ── State machine: idle → uploading → tier_select → summarising → done
  const [stage, setStage]           = useState("idle");      // idle | uploading | tier_select | summarising | done
  const [uploadedDoc, setUploadedDoc] = useState(null);       // { paper_id, title, num_chunks }
  const [selectedTier, setSelectedTier] = useState("intermediate");
  const [summary, setSummary]       = useState(null);         // { summary_markdown, from_cache, created_at }
  const [processingMsg, setProcessingMsg] = useState("");
  const [rateLimitSecs, setRateLimitSecs] = useState(null);
  const [toast, setToast]           = useState({ msg: "", type: "", visible: false });
  const [dragOver, setDragOver]     = useState(false);
  const [showSummary, setShowSummary] = useState(true);

  // history of (uploadedDoc + summary) pairs for the sidebar
  const [history, setHistory]       = useState([]);
  const [activeIdx, setActiveIdx]   = useState(null);

  const fileInputRef = useRef(null);
  const toastTimer   = useRef(null);

  const showToast = (msg, type = "") => {
    setToast({ msg, type, visible: true });
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(t => ({ ...t, visible: false })), 5000);
  };

  // ── Step 1: upload PDF ────────────────────────────────────────────────────
  const handleFile = async (file) => {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      showToast("Only PDF files are supported.", "error");
      return;
    }
    setStage("uploading");
    setProcessingMsg("Uploading PDF…");
    setSummary(null);
    setUploadedDoc(null);
    try {
      const res = await apiUpload(file);           // POST /upload
      setUploadedDoc(res);                          // { paper_id, title, num_chunks, status }
      setStage("tier_select");
      setProcessingMsg("");
    } catch (err) {
      const e = parseApiError(err);
      if (e.retry_after) setRateLimitSecs(e.retry_after);
      showToast(`Upload failed: ${e.detail}`, "error");
      setStage("idle");
      setProcessingMsg("");
    }
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  // ── Step 2: generate summary for chosen tier ──────────────────────────────
  const handleGenerateSummary = async () => {
    if (!uploadedDoc) return;
    setStage("summarising");
    setProcessingMsg(selectedTier === "expert" ? "Generating expert summary… (may take ~15 s)" : "Generating summary…");
    try {
      let res;
      // Try cache first — never triggers a new LLM call
      try {
        res = await apiGetCached(uploadedDoc.paper_id, selectedTier);
      } catch (cacheErr) {
        if (cacheErr?.response?.status === 404) {
          res = await apiGenerate(uploadedDoc.paper_id, selectedTier);  // POST /summarize
        } else {
          throw cacheErr;
        }
      }
      setSummary(res);
      const entry = { doc: uploadedDoc, tier: selectedTier, summary: res };
      setHistory(prev => {
        const next = [entry, ...prev];
        setActiveIdx(0);
        return next;
      });
      setStage("done");
      setShowSummary(true);
      setProcessingMsg("");
      showToast(`✓ ${uploadedDoc.title || "Document"} · ${selectedTier}${res.from_cache ? " · cached" : ""}`);
    } catch (err) {
      const e = parseApiError(err);
      if (e.retry_after) setRateLimitSecs(e.retry_after);
      showToast(`Summary failed: ${e.detail}`, "error");
      setStage("tier_select");   // let user retry with same upload
      setProcessingMsg("");
    }
  };

  // ── Load a history entry ──────────────────────────────────────────────────
  const loadHistory = (idx) => {
    const entry = history[idx];
    setUploadedDoc(entry.doc);
    setActiveIdx(idx);

    if (entry.summary) {
      // Has a cached summary — show it directly
      setSelectedTier(entry.tier);
      setSummary(entry.summary);
      setStage("done");
      setShowSummary(true);
    } else {
      // Paper exists but no summary yet — go to tier select so user can generate
      setSelectedTier("intermediate");
      setSummary(null);
      setStage("tier_select");
    }
  };

  // ── Reset to upload another ───────────────────────────────────────────────
  const resetToIdle = () => {
    setStage("idle");
    setUploadedDoc(null);
    setSummary(null);
    setProcessingMsg("");
  };

  const isWorking = stage === "uploading" || stage === "summarising";
  const activeTierMeta = TIERS.find(t => t.id === selectedTier);

  const css = `
    @keyframes fadeUp { from{opacity:0;transform:translateY(12px)} to{opacity:1;transform:none} }
    @keyframes spin   { to{transform:rotate(360deg)} }
    @keyframes pulse  { 0%,100%{opacity:1} 50%{opacity:.4} }
    * { box-sizing:border-box; scrollbar-width:thin; scrollbar-color:rgba(0,0,0,.15) transparent; }
    *::-webkit-scrollbar { width:4px; }
    *::-webkit-scrollbar-thumb { background:rgba(0,0,0,.12); border-radius:2px; }
  `;

  return (
    <>
      <style>{css}</style>
      <div style={{
        display: "grid", gridTemplateColumns: "280px 1fr", gridTemplateRows: "56px 1fr",
        height: "100vh", background: "#f5f0e8", color: "#1a1714",
        fontFamily: "Space Grotesk, sans-serif", overflow: "hidden",
      }}>

        {/* ── Topbar ──────────────────────────────────────────────────────── */}
        <header style={{
          gridColumn: "1/-1", display: "flex", alignItems: "center",
          justifyContent: "space-between", padding: "0 20px",
          borderBottom: "1px solid rgba(255,255,255,.07)", background: "#f5f0e8", zIndex: 10,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div style={{
              width: 30, height: 30, borderRadius: 9,
              background: "linear-gradient(135deg,#6b4f2a,#9b6b3a)",
              display: "flex", alignItems: "center", justifyContent: "center",
            }}>
              <svg viewBox="0 0 16 16" fill="none" width={16} height={16}>
                <path d="M3 4h10M3 8h7M3 12h5" stroke="white" strokeWidth="1.5" strokeLinecap="round"/>
                <circle cx="13" cy="11" r="2.5" stroke="white" strokeWidth="1.2"/>
                <path d="M15 13l1.5 1.5" stroke="white" strokeWidth="1.2" strokeLinecap="round"/>
              </svg>
            </div>
            <span style={{ fontFamily: "Instrument Serif, serif", fontSize: 22, letterSpacing: -.3 }}>
              Sum<span style={{ color: "#8b5e2a" }}>mora</span>
            </span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, fontFamily: "JetBrains Mono, monospace", color: "#9a9183" }}>
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#2d7a4f", display: "inline-block" }} />
            localhost:8000
          </div>
        </header>

        {/* ── Sidebar ──────────────────────────────────────────────────────── */}
        <aside style={{
          background: "#ede8dc", borderRight: "1px solid rgba(255,255,255,.07)",
          display: "flex", flexDirection: "column", overflow: "hidden",
        }}>
          {/* Upload zone */}
          <div style={{ padding: 16, borderBottom: "1px solid rgba(255,255,255,.07)" }}>
            <div style={{ fontSize: 10, fontFamily: "JetBrains Mono, monospace", letterSpacing: "1.5px", textTransform: "uppercase", color: "#9a9183", marginBottom: 12 }}>
              Upload PDF
            </div>
            <div
              onDragOver={e => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={e => { e.preventDefault(); setDragOver(false); handleFile(e.dataTransfer.files[0]); }}
              onClick={() => !isWorking && fileInputRef.current?.click()}
              style={{
                border: `1.5px dashed ${dragOver ? "#6b4f2a" : "rgba(0,0,0,.18)"}`,
                borderRadius: 14, padding: "20px 16px", textAlign: "center",
                cursor: isWorking ? "default" : "pointer", transition: "all .2s",
                background: dragOver ? "rgba(107,79,42,.07)" : "transparent",
                opacity: isWorking ? .5 : 1,
              }}
            >
              <input ref={fileInputRef} type="file" accept=".pdf" style={{ display: "none" }}
                onChange={e => handleFile(e.target.files?.[0])} />
              <div style={{ fontSize: 26, marginBottom: 6 }}>📄</div>
              <div style={{ fontSize: 12, color: "#6b6456", lineHeight: 1.6 }}>
                Drop a <strong style={{ color: "#8b5e2a" }}>PDF</strong><br />or click to browse
              </div>
            </div>

            {/* Processing status */}
            {isWorking && (
              <div style={{
                marginTop: 10, padding: "9px 12px", background: "#e4dfd2",
                borderRadius: 10, border: "1px solid rgba(255,255,255,.07)",
                fontSize: 12, color: "#6b6456", display: "flex", alignItems: "center", gap: 8,
              }}>
                <Spinner />
                {processingMsg}
              </div>
            )}
          </div>

          {/* History */}
          <div style={{ fontSize: 10, fontFamily: "JetBrains Mono, monospace", letterSpacing: "1.5px", textTransform: "uppercase", color: "#9a9183", padding: "14px 16px 4px" }}>
            Recent
          </div>
          <div style={{ flex: 1, overflowY: "auto", padding: 8 }}>
            {history.length === 0 ? (
              <div style={{ padding: 20, textAlign: "center", color: "#9a9183", fontSize: 12, lineHeight: 1.8 }}>
                No summaries yet.<br />Upload a PDF to start.
              </div>
            ) : history.map((entry, i) => {
              const tm = TIERS.find(t => t.id === entry.tier);
              const isActive = i === activeIdx;
              return (
                <div key={i} onClick={() => loadHistory(i)} style={{
                  padding: "10px 12px", borderRadius: 10, cursor: "pointer", marginBottom: 4,
                  border: `1px solid ${isActive ? "rgba(124,110,247,.3)" : "transparent"}`,
                  background: isActive ? "rgba(107,79,42,.07)" : "transparent",
                  transition: "all .15s",
                }}>
                  <div style={{ fontSize: 12, color: "#1a1714", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", fontWeight: 500 }}>
                    {entry.doc?.title || entry.doc?.filename || "Document"}
                  </div>
                  <div style={{ fontSize: 11, color: "#9a9183", marginTop: 2, fontFamily: "JetBrains Mono, monospace", display: "flex", gap: 8, alignItems: "center" }}>
                    <span style={{ color: "#8b5e2a" }}>{entry.doc?.num_chunks} chunks</span>
                    {tm && entry.tier && <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                      <span style={{ width: 6, height: 6, borderRadius: "50%", background: tm.dot, display: "inline-block" }} />
                      {tm.label}
                    </span>}
                    {!entry.tier && <span style={{ color: "#9a9183" }}>no summary yet</span>}
                    {entry.summary?.from_cache && <span style={{ color: "#2d7a4f" }}>cached</span>}
                  </div>
                </div>
              );
            })}
          </div>
        </aside>

        {/* ── Main panel ───────────────────────────────────────────────────── */}
        <main style={{ display: "flex", flexDirection: "column", overflow: "hidden", position: "relative" }}>

          {/* ── IDLE: empty state ─────────────────────────────────────────── */}
          {stage === "idle" && (
            <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 20, padding: 40, textAlign: "center", animation: "fadeUp .4s ease" }}>
              <h2 style={{ fontFamily: "Instrument Serif, serif", fontSize: 34, fontWeight: 400, margin: 0 }}>
                Research Paper Summariser
              </h2>
              <p style={{ fontSize: 14, color: "#6b6456", maxWidth: 380, lineHeight: 1.85, margin: 0 }}>
                Upload a PDF and choose your depth level — we'll generate a structured summary powered by your backend.
              </p>
              <div style={{ display: "flex", gap: 12, marginTop: 4, flexWrap: "wrap", justifyContent: "center" }}>
                {[
                  ["01", "Upload a PDF"],
                  ["02", "Choose a depth level"],
                ].map(([num, step]) => (
                  <div key={num} style={{
                    background: "#ede8dc", border: "1px solid rgba(255,255,255,.08)",
                    borderRadius: 12, padding: "14px 16px", fontSize: 12, color: "#6b6456",
                    display: "flex", alignItems: "flex-start", gap: 8, minWidth: 140, textAlign: "left",
                  }}>
                    <span style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 11, color: "#8b5e2a", flexShrink: 0 }}>{num}</span>
                    {step}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* ── UPLOADING ─────────────────────────────────────────────────── */}
          {stage === "uploading" && (
            <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 16, animation: "fadeUp .3s ease" }}>
              <Spinner />
              <span style={{ fontSize: 13, color: "#6b6456", fontFamily: "JetBrains Mono, monospace" }}>Uploading PDF…</span>
            </div>
          )}

          {/* ── TIER SELECT: uploaded, pick level + confirm ───────────────── */}
          {stage === "tier_select" && uploadedDoc && (
            <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", padding: "32px 40px", animation: "fadeUp .35s ease" }}>
              <div style={{ width: "100%", maxWidth: 480 }}>
                {/* Uploaded doc info */}
                <div style={{
                  background: "#ede8dc", border: "1px solid rgba(255,255,255,.08)",
                  borderRadius: 14, padding: "14px 16px", marginBottom: 24,
                  display: "flex", alignItems: "center", gap: 12,
                }}>
                  <div style={{ fontSize: 24 }}>📄</div>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: "#1a1714" }}>
                      {uploadedDoc.title || "Uploaded document"}
                    </div>
                    <div style={{ fontSize: 11, color: "#9a9183", fontFamily: "JetBrains Mono, monospace", marginTop: 3 }}>
                      {uploadedDoc.num_chunks} chunks · paper_id: {uploadedDoc.paper_id?.slice(0, 10)}…
                    </div>
                  </div>
                  <div style={{ marginLeft: "auto", fontSize: 10, padding: "3px 10px", borderRadius: 20, background: "rgba(45,122,79,.1)", color: "#2d7a4f", fontFamily: "JetBrains Mono, monospace" }}>
                    uploaded ✓
                  </div>
                </div>

                {/* Tier picker */}
                <div style={{ fontSize: 10, fontFamily: "JetBrains Mono, monospace", letterSpacing: "1.5px", textTransform: "uppercase", color: "#9a9183", marginBottom: 12 }}>
                  Summary Depth
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 24 }}>
                  {TIERS.map(t => (
                    <button key={t.id} onClick={() => setSelectedTier(t.id)} style={{
                      display: "flex", alignItems: "center", gap: 12, padding: "12px 14px",
                      borderRadius: 12, cursor: "pointer", textAlign: "left", width: "100%",
                      border: `1.5px solid ${selectedTier === t.id ? "rgba(107,79,42,.5)" : "rgba(0,0,0,.09)"}`,
                      background: selectedTier === t.id ? "rgba(107,79,42,.08)" : "transparent",
                      transition: "all .15s",
                    }}>
                      <span style={{ width: 10, height: 10, borderRadius: "50%", background: t.dot, flexShrink: 0, display: "inline-block" }} />
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: 13, fontWeight: 600, color: selectedTier === t.id ? "#a06b2a" : "#2e2b26", fontFamily: "Space Grotesk, sans-serif" }}>
                          {t.label}
                        </div>
                        <div style={{ fontSize: 11, color: "#9a9183", marginTop: 2 }}>{t.desc}</div>
                      </div>
                      {selectedTier === t.id && (
                        <span style={{ fontSize: 13, color: "#8b5e2a", fontWeight: 700 }}>✓</span>
                      )}
                    </button>
                  ))}
                </div>

                {rateLimitSecs && <RateLimitBanner retryAfter={rateLimitSecs} onDismiss={() => setRateLimitSecs(null)} />}

                {/* Generate button */}
                <button
                  onClick={handleGenerateSummary}
                  disabled={!!rateLimitSecs}
                  style={{
                    width: "100%", padding: "13px 0", borderRadius: 12, border: "none",
                    cursor: rateLimitSecs ? "default" : "pointer",
                    background: "linear-gradient(135deg, #6b4f2a, #9b6b3a)",
                    color: "#fff", fontSize: 14, fontWeight: 600,
                    fontFamily: "Space Grotesk, sans-serif", letterSpacing: .3,
                    opacity: rateLimitSecs ? .4 : 1, transition: "opacity .15s",
                  }}
                  onMouseEnter={e => { if (!rateLimitSecs) e.currentTarget.style.opacity = ".82"; }}
                  onMouseLeave={e => { e.currentTarget.style.opacity = rateLimitSecs ? ".4" : "1"; }}
                >
                  Generate {activeTierMeta?.label} Summary →
                </button>

                <div style={{ marginTop: 10, textAlign: "center" }}>
                  <button onClick={resetToIdle} style={{ background: "none", border: "none", color: "#9a9183", fontSize: 12, cursor: "pointer", fontFamily: "JetBrains Mono, monospace" }}>
                    ← upload a different file
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* ── SUMMARISING ───────────────────────────────────────────────── */}
          {stage === "summarising" && (
            <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 16, animation: "fadeUp .3s ease" }}>
              <Spinner />
              <span style={{ fontSize: 13, color: "#6b6456", fontFamily: "JetBrains Mono, monospace", animation: "pulse 2s ease infinite" }}>
                {processingMsg}
              </span>
            </div>
          )}

          {/* ── DONE: show summary ────────────────────────────────────────── */}
          {stage === "done" && summary && uploadedDoc && (
            <div style={{ flex: 1, overflowY: "auto", padding: "28px 32px", animation: "fadeUp .4s ease" }}>
              {/* Header */}
              <div style={{ display: "flex", alignItems: "flex-start", gap: 16, marginBottom: 20 }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 11, fontFamily: "JetBrains Mono, monospace", color: "#9a9183", marginBottom: 6 }}>
                    📄 {uploadedDoc.title || "Document"} · {uploadedDoc.num_chunks} chunks · paper_id: {uploadedDoc.paper_id?.slice(0, 10)}…
                  </div>
                  <h2 style={{ fontFamily: "Instrument Serif, serif", fontSize: 26, fontWeight: 400, margin: 0, color: "#1a1714" }}>
                    {uploadedDoc.title || "Summary"}
                  </h2>
                </div>
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexShrink: 0 }}>
                  {/* Tier badge */}
                  {activeTierMeta && (
                    <span style={{
                      fontSize: 11, padding: "4px 10px", borderRadius: 20,
                      border: "1px solid rgba(255,255,255,.1)",
                      color: activeTierMeta.dot, fontFamily: "JetBrains Mono, monospace",
                      display: "flex", alignItems: "center", gap: 5,
                    }}>
                      <span style={{ width: 6, height: 6, borderRadius: "50%", background: activeTierMeta.dot, display: "inline-block" }} />
                      {activeTierMeta.label}
                    </span>
                  )}
                  {summary.from_cache && (
                    <span style={{ fontSize: 11, padding: "4px 10px", borderRadius: 20, background: "rgba(45,122,79,.1)", color: "#2d7a4f", fontFamily: "JetBrains Mono, monospace" }}>
                      cached
                    </span>
                  )}
                </div>
              </div>

              {/* Summary content */}
              <div style={{
                background: "#ede8dc", border: "1px solid rgba(255,255,255,.08)",
                borderRadius: 16, padding: "22px 24px",
                fontSize: 14, color: "#2e2b26", lineHeight: 1.9,
                fontFamily: "Space Grotesk, sans-serif",
              }} className="markdown-body">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {summary.summary_markdown}
                </ReactMarkdown>
              </div>

              {/* Footer actions */}
              <div style={{ marginTop: 16, display: "flex", gap: 10, flexWrap: "wrap" }}>
                <button onClick={resetToIdle} style={{
                  padding: "9px 16px", borderRadius: 10, border: "1px solid rgba(255,255,255,.1)",
                  background: "transparent", color: "#6b6456", fontSize: 12, cursor: "pointer",
                  fontFamily: "Space Grotesk, sans-serif", transition: "all .15s",
                }}
                  onMouseEnter={e => e.currentTarget.style.borderColor = "rgba(107,79,42,.4)"}
                  onMouseLeave={e => e.currentTarget.style.borderColor = "rgba(0,0,0,.1)"}
                >
                  ← Upload another PDF
                </button>
                {/* Re-summarise at a different tier */}
                <button onClick={() => { setStage("tier_select"); setSummary(null); }} style={{
                  padding: "9px 16px", borderRadius: 10, border: "1px solid rgba(255,255,255,.1)",
                  background: "transparent", color: "#6b6456", fontSize: 12, cursor: "pointer",
                  fontFamily: "Space Grotesk, sans-serif", transition: "all .15s",
                }}
                  onMouseEnter={e => e.currentTarget.style.borderColor = "rgba(107,79,42,.4)"}
                  onMouseLeave={e => e.currentTarget.style.borderColor = "rgba(0,0,0,.1)"}
                >
                  ↺ Change depth level
                </button>
              </div>

              {summary.created_at && (
                <div style={{ marginTop: 12, fontSize: 11, color: "#b0a898", fontFamily: "JetBrains Mono, monospace" }}>
                  generated {new Date(summary.created_at).toLocaleString()}
                </div>
              )}
            </div>
          )}
        </main>

        <Toast {...toast} />
      </div>
    </>
  );
}