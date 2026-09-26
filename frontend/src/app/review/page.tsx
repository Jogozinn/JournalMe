"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { useAccount } from "@/components/account-provider";
import { EmptyState, ErrorState, PageHeader, Pnl, Skeleton } from "@/components/ui";
import { api, dateTime, money, quantity } from "@/lib/api";
import type { Playbook, ReviewStatus, Trade } from "@/lib/types";

type Queue = {
  items: (Trade & { review: ReviewStatus })[];
  total: number;
  counts: { unreviewed: number; partial: number; complete: number };
  completion_percent: number;
};

export default function ReviewQueuePage() {
  const { account, loading } = useAccount();
  const [queue, setQueue] = useState<Queue | null>(null);
  const [playbooks, setPlaybooks] = useState<Playbook[]>([]);
  const [statusFilter, setStatusFilter] = useState("unreviewed");
  const [missingPlaybook, setMissingPlaybook] = useState(false);
  const [missingScreenshot, setMissingScreenshot] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [bulkPlaybook, setBulkPlaybook] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [focusMode, setFocusMode] = useState(false);
  const [focusIndex, setFocusIndex] = useState(0);

  const load = () => {
    if (!account) return;
    const params = new URLSearchParams({ account_id: account.id });
    if (statusFilter) params.set("review_status", statusFilter);
    if (missingPlaybook) params.set("missing_playbook", "true");
    if (missingScreenshot) params.set("missing_screenshot", "true");
    setError("");
    void Promise.allSettled([
      api<Queue>(`/review-queue?${params}`),
      api<Playbook[]>("/playbooks?active=true"),
    ]).then(([nextQueue, nextPlaybooks]) => {
      if (nextQueue.status === "rejected") {
        setQueue(null);
        setError(nextQueue.reason instanceof Error ? nextQueue.reason.message : "Review queue could not be loaded.");
        return;
      }
      setQueue(nextQueue.value);
      setPlaybooks(nextPlaybooks.status === "fulfilled" ? nextPlaybooks.value : []);
      setSelected([]);
      setFocusIndex(0);
    });
  };

  useEffect(load, [account, statusFilter, missingPlaybook, missingScreenshot]);

  useEffect(() => {
    if (!focusMode || !queue?.items.length) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setFocusMode(false);
      if (event.key === "ArrowRight" || event.key === "ArrowDown") {
        event.preventDefault();
        setFocusIndex((value) => Math.min(value + 1, queue.items.length - 1));
      }
      if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
        event.preventDefault();
        setFocusIndex((value) => Math.max(value - 1, 0));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [focusMode, queue]);

  async function assignBulk() {
    if (!bulkPlaybook || !selected.length) return;
    setSaving(true);
    try {
      await Promise.all(selected.map((tradeId) => api(`/trades/${tradeId}/playbooks`, {
        method: "PUT",
        body: JSON.stringify({ primary_playbook_id: bulkPlaybook, secondary_playbook_ids: [] }),
      })));
      load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Playbook assignment failed.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <Skeleton rows={6} />;
  if (!account) return <EmptyState title="Create an account first." copy="The review queue belongs to one account." href="/" action="Set up account" />;

  const focusTrade = queue?.items[focusIndex] ?? null;

  return (
    <>
      <PageHeader
        eyebrow="Deliberate practice"
        title="Review Queue"
        description="Clear the queue one decision at a time."
        action={<div className="header-actions">
          <Link className="button" href={`/reviews/weekly/${new Date().toISOString().slice(0, 10)}`}>Weekly review</Link>
          <Link className="button" href={`/reviews/monthly/${new Date().toISOString().slice(0, 7)}-01`}>Monthly review</Link>
          {queue?.items.length ? <button className="button primary" type="button" onClick={() => setFocusMode(true)}>Focus review</button> : null}
        </div>}
      />
      {error && <ErrorState message={error} />}
      {queue && <section className="review-progress card premium-review-progress">
        <div><strong>{queue.completion_percent}%</strong><span>all-time completion</span></div>
        <div className="linear-progress"><i style={{ width: `${queue.completion_percent}%` }} /></div>
        <div className="review-counts"><span>{queue.counts.unreviewed} unreviewed</span><span>{queue.counts.partial} partial</span><span>{queue.counts.complete} complete</span></div>
      </section>}
      <section className="queue-toolbar card premium-filter-bar">
        <div className="segmented">
          {[["unreviewed", "Unreviewed"], ["partial", "Partial"], ["complete", "Complete"], ["", "All"]].map(([value, label]) => <button key={label} className={statusFilter === value ? "selected" : ""} onClick={() => setStatusFilter(value)}>{label}</button>)}
        </div>
        <label><input type="checkbox" checked={missingPlaybook} onChange={(event) => setMissingPlaybook(event.target.checked)} /> Missing playbook</label>
        <label><input type="checkbox" checked={missingScreenshot} onChange={(event) => setMissingScreenshot(event.target.checked)} /> Missing screenshot</label>
      </section>
      {selected.length > 0 && <section className="bulk-bar card">
        <strong>{selected.length} selected</strong>
        <select value={bulkPlaybook} onChange={(event) => setBulkPlaybook(event.target.value)}><option value="">Choose primary playbook</option>{playbooks.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select>
        <button className="button primary" onClick={assignBulk} disabled={!bulkPlaybook || saving}>{saving ? "Assigning…" : "Assign playbook"}</button>
      </section>}
      {!queue ? <Skeleton rows={6} /> : !queue.items.length ? (
        <EmptyState title="Nothing matches this queue." copy="Your review practice is caught up for these filters." href="/days" action="Open trading days" />
      ) : <section className="queue-list premium-queue-list">
        {queue.items.map((trade, index) => <article className="card queue-item" key={trade.id}>
          <label className="queue-select"><input type="checkbox" checked={selected.includes(trade.id)} onChange={(event) => setSelected(event.target.checked ? [...selected, trade.id] : selected.filter((id) => id !== trade.id))} /><span className="sr-only">Select {trade.symbol}</span></label>
          <button className="queue-trade-button" type="button" onClick={() => { setFocusIndex(index); setFocusMode(true); }}>
            <div><strong>{trade.symbol}</strong><span className={`side-token ${trade.side}`}>{trade.side}</span>{trade.source === "manual" && <span className="source-label">Manual</span>}</div>
            <p>{quantity(trade.quantity, true)} · {dateTime(trade.entry_timestamp)}</p>
          </button>
          <div className="missing-list"><strong className={`status-text ${trade.review.status}`}>{trade.review.status}</strong><span>{trade.review.missing.slice(0, 3).join(" · ") || "All requirements complete"}</span></div>
          <Pnl value={trade.net_pnl}>{money(trade.net_pnl)}</Pnl>
          <Link className="button" href={`/timeline/${trade.entry_timestamp.slice(0, 10)}`}>Open day</Link>
        </article>)}
      </section>}

      {focusMode && focusTrade && queue && (
        <div className="focus-review-backdrop" role="presentation" onMouseDown={() => setFocusMode(false)}>
          <section className="focus-review" role="dialog" aria-modal="true" aria-label="Focus review" onMouseDown={(event) => event.stopPropagation()}>
            <header>
              <div><p className="eyebrow">Focus review</p><h2>{focusTrade.symbol}</h2><p>{dateTime(focusTrade.entry_timestamp)}</p></div>
              <button className="icon-button" type="button" onClick={() => setFocusMode(false)} aria-label="Close focus review">×</button>
            </header>
            <div className="focus-progress"><i style={{ width: `${((focusIndex + 1) / queue.items.length) * 100}%` }} /></div>
            <div className="focus-review-result">
              <div><span className={`side-token ${focusTrade.side}`}>{focusTrade.side}</span><strong>{quantity(focusTrade.quantity, true)}</strong></div>
              <Pnl value={focusTrade.net_pnl}>{money(focusTrade.net_pnl)}</Pnl>
            </div>
            <div className="focus-review-missing">
              <span>Still needed</span>
              <p>{focusTrade.review.missing.length ? focusTrade.review.missing.join(" · ") : "This trade meets the current review requirements."}</p>
            </div>
            <div className="focus-review-actions">
              <Link className="button primary" href={`/trades/${focusTrade.id}?queue=review`}>Review this trade</Link>
              <Link className="button" href={`/timeline/${focusTrade.entry_timestamp.slice(0, 10)}`}>Open session</Link>
            </div>
            <footer>
              <button type="button" disabled={focusIndex === 0} onClick={() => setFocusIndex(Math.max(focusIndex - 1, 0))}>← Previous</button>
              <span>{focusIndex + 1} of {queue.items.length}</span>
              <button type="button" disabled={focusIndex >= queue.items.length - 1} onClick={() => setFocusIndex(Math.min(focusIndex + 1, queue.items.length - 1))}>Next →</button>
            </footer>
          </section>
        </div>
      )}
    </>
  );
}
