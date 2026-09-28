"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { AuthenticatedImage } from "@/components/authenticated-assets";
import { ErrorState, PageHeader, Skeleton } from "@/components/ui";
import { api, dateTime } from "@/lib/api";

type CaptureItem = {
  id: string;
  account_id: string | null;
  captured_at: string;
  created_at: string;
  event_type: "entry" | "exit" | "update" | "wait";
  episode_id?: string | null;
  phase?: string | null;
  recorded_live?: boolean;
  symbol: string | null;
  side: "long" | "short" | null;
  note: string | null;
  setup_tags: string[];
  execution_tags: string[];
  emotion_tags: string[];
  platform: string | null;
  page_url: string | null;
  page_title: string | null;
  source: string | null;
  match_status: "unmatched" | "suggested" | "matched" | string;
  matched_trade_id: string | null;
  match_score: number | null;
  has_screenshot?: boolean;
  screenshot_url: string | null;
};

type Filter = "all" | "matched" | "suggested" | "unmatched";

function statusLabel(value: string): string {
  if (value === "matched") return "Matched";
  if (value === "suggested") return "Possible match";
  return "Unmatched";
}

export default function CapturesPage() {
  const [captures, setCaptures] = useState<CaptureItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [loading, setLoading] = useState(true);
  const [reconciling, setReconciling] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [error, setError] = useState("");

  async function load(selectFromUrl = false) {
    setError("");
    try {
      const rows = await api<CaptureItem[]>("/captures?limit=100", { cache: "no-cache" });
      setCaptures(rows);
      if (selectFromUrl) {
        const requested = new URLSearchParams(window.location.search).get("selected");
        if (requested && rows.some((item) => item.id === requested)) setSelectedId(requested);
        else if (rows.length) setSelectedId(rows[0].id);
      } else if (!selectedId && rows.length) {
        setSelectedId(rows[0].id);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Captures could not be loaded.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load(true);
    // selectedId intentionally initializes from the URL only once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const counts = useMemo(() => ({
    all: captures.length,
    matched: captures.filter((item) => item.match_status === "matched").length,
    suggested: captures.filter((item) => item.match_status === "suggested").length,
    unmatched: captures.filter((item) => !["matched", "suggested"].includes(item.match_status)).length,
  }), [captures]);

  const visible = useMemo(
    () => captures.filter((item) => {
      if (filter === "all") return true;
      if (filter === "unmatched") return !["matched", "suggested"].includes(item.match_status);
      return item.match_status === filter;
    }),
    [captures, filter],
  );

  const selected = captures.find((item) => item.id === selectedId) ?? null;

  function choose(id: string) {
    setSelectedId(id);
    const url = new URL(window.location.href);
    url.searchParams.set("selected", id);
    window.history.replaceState(null, "", url.toString());
  }

  async function reconcile() {
    setReconciling(true);
    setError("");
    try {
      await api("/captures/reconcile", { method: "POST" });
      await load(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Capture matching could not be refreshed.");
    } finally {
      setReconciling(false);
    }
  }

  async function removeCapture(item: CaptureItem) {
    if (!window.confirm("Remove this capture and its screenshot? The matched trade and journal will not be deleted.")) return;
    setDeletingId(item.id);
    setError("");
    try {
      await api(`/captures/${item.id}`, { method: "DELETE" });
      const remaining = captures.filter((capture) => capture.id !== item.id);
      setCaptures(remaining);
      if (selectedId === item.id) {
        const next = remaining[0]?.id ?? null;
        setSelectedId(next);
        const url = new URL(window.location.href);
        if (next) url.searchParams.set("selected", next);
        else url.searchParams.delete("selected");
        window.history.replaceState(null, "", url.toString());
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Capture could not be removed.");
    } finally {
      setDeletingId(null);
    }
  }

  async function confirmSuggestedMatch(item: CaptureItem) {
    if (!item.matched_trade_id) return;
    setConfirmingId(item.id);
    setError("");
    try {
      await api(`/captures/${item.id}/match/${item.matched_trade_id}`, { method: "POST" });
      await load(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Suggested match could not be confirmed.");
    } finally {
      setConfirmingId(null);
    }
  }

  if (loading) return <Skeleton rows={6} />;

  return (
    <>
      <PageHeader
        title="Captures"
        description="Screenshots and context from JournalMe Companion land here, even when the JournalMe tab was closed."
        action={<button className="button" type="button" onClick={() => void reconcile()} disabled={reconciling}>{reconciling ? "Matching..." : "Refresh matches"}</button>}
      />
      {error && <ErrorState message={error} />}

      <section className="capture-summary-grid">
        <button type="button" className={filter === "all" ? "active" : ""} onClick={() => setFilter("all")}><span>All captures</span><strong>{counts.all}</strong></button>
        <button type="button" className={filter === "matched" ? "active" : ""} onClick={() => setFilter("matched")}><span>Matched</span><strong>{counts.matched}</strong></button>
        <button type="button" className={filter === "suggested" ? "active" : ""} onClick={() => setFilter("suggested")}><span>Possible matches</span><strong>{counts.suggested}</strong></button>
        <button type="button" className={filter === "unmatched" ? "active" : ""} onClick={() => setFilter("unmatched")}><span>Unmatched</span><strong>{counts.unmatched}</strong></button>
      </section>

      {!captures.length ? (
        <section className="empty-state card capture-empty">
          <h2>No Companion captures yet</h2>
          <p>Use Alt+C from a chart, add context in the Chrome sidebar, and save. The capture will appear here.</p>
          <p className="muted">Open JournalMe Companion in Chrome and choose Connect web.</p>
        </section>
      ) : (
        <section className="capture-workspace">
          <div className="capture-list" aria-label="Saved captures">
            {visible.map((item) => (
              <div className="capture-list-row" key={item.id}>
                <button
                  type="button"
                  className={`capture-list-item ${item.id === selectedId ? "active" : ""}`}
                  onClick={() => choose(item.id)}
                >
                  <div className="capture-list-topline">
                    <strong>{item.symbol || "WAIT"}</strong>
                    {item.side && <span className={`side-token ${item.side}`}>{item.side}</span>}
                    <span className={`capture-match ${item.match_status}`}>{statusLabel(item.match_status)}</span>
                  </div>
                  <span>{item.phase ? item.phase.replaceAll("_", " ") : item.event_type} · {item.platform || "Browser"}</span>
                  <small>{dateTime(item.captured_at)}</small>
                  {item.note && <p>{item.note}</p>}
                </button>
                <button
                  type="button"
                  className="capture-remove"
                  title="Remove capture"
                  aria-label={`Remove ${item.symbol || "capture"}`}
                  disabled={deletingId === item.id}
                  onClick={() => void removeCapture(item)}
                >
                  ×
                </button>
              </div>
            ))}
          </div>

          <div className="capture-detail card">
            {selected ? (
              <>
                <div className="capture-detail-head">
                  <div>
                    <span className="capture-kicker">{selected.phase ? selected.phase.replaceAll("_", " ") : selected.event_type} · {selected.platform || "Browser"}{selected.recorded_live === false ? " · added later" : ""}</span>
                    <h2>{selected.symbol || "Wait capture"}{selected.side ? ` · ${selected.side}` : ""}</h2>
                    <p>{dateTime(selected.captured_at)}</p>
                  </div>
                  <span className={`capture-match ${selected.match_status}`}>{statusLabel(selected.match_status)}</span>
                </div>

                {selected.screenshot_url ? (
                  <div className="capture-image-frame">
                    <AuthenticatedImage path={selected.screenshot_url} alt={`JournalMe capture ${selected.symbol || "WAIT"}`} />
                  </div>
                ) : (
                  <div className="capture-image-frame capture-text-only">Text-only Companion moment</div>
                )}

                {selected.note && (
                  <div className="capture-note-wrap">
                    <span>What I was seeing</span>
                    <blockquote className="capture-note">{selected.note}</blockquote>
                  </div>
                )}

                <div className="capture-tag-sections">
                  {selected.setup_tags.length > 0 && <div><span>Setup and context</span><div className="capture-tags">{selected.setup_tags.map((tag) => <em key={tag}>{tag}</em>)}</div></div>}
                  {selected.execution_tags.length > 0 && <div><span>Execution</span><div className="capture-tags">{selected.execution_tags.map((tag) => <em key={tag}>{tag}</em>)}</div></div>}
                  {selected.emotion_tags.length > 0 && <div><span>State</span><div className="capture-tags">{selected.emotion_tags.map((tag) => <em key={tag}>{tag}</em>)}</div></div>}
                </div>

                <div className="capture-detail-actions">
                  {selected.match_status === "matched" && selected.matched_trade_id && (
                    <Link className="button primary" href={`/trades/${selected.matched_trade_id}?capture=${selected.id}`}>Open matched trade</Link>
                  )}
                  {selected.match_status === "suggested" && selected.matched_trade_id && (
                    <>
                      <Link className="button" href={`/trades/${selected.matched_trade_id}?capture=${selected.id}`}>Review possible trade</Link>
                      <button className="button primary" type="button" disabled={confirmingId === selected.id} onClick={() => void confirmSuggestedMatch(selected)}>
                        {confirmingId === selected.id ? "Confirming..." : "Confirm match"}
                      </button>
                    </>
                  )}
                  {selected.page_url && <a className="button" href={selected.page_url} target="_blank" rel="noreferrer">Open source chart</a>}
                  <button className="button quiet danger-text" type="button" disabled={deletingId === selected.id} onClick={() => void removeCapture(selected)}>
                    {deletingId === selected.id ? "Removing..." : "Remove capture"}
                  </button>
                </div>
              </>
            ) : <p className="muted">Choose a capture to inspect it.</p>}
          </div>
        </section>
      )}
    </>
  );
}
