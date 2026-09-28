"use client";

import { DragEvent, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { useAccount } from "@/components/account-provider";
import { Icon } from "@/components/icons";
import { ErrorState, PageHeader } from "@/components/ui";
import { api, type ImportIssue } from "@/lib/api";

type Preview = {
  session_id: string;
  status: string;
  reports: {
    filename: string;
    type: string;
    rows: number;
    duplicate_rows: number;
    status: string;
  }[];
  coverage: { start: string | null; end: string | null };
  detected_accounts: string[];
  canonical_trades: number;
  new_trades: number;
  existing_trades: number;
  duplicate_rows: number;
  unmatched_fills: number;
  linked_filled_orders: number;
  canceled_unfilled_orders: number;
  unmatched_filled_orders: number;
  unmatched_orders: number;
  warnings: string[];
  errors: ImportIssue[];
};

function issueMessage(issue: ImportIssue): string {
  return (
    `${issue.filename}, CSV row ${issue.row_number}, column ${issue.source_column} ` +
    `(${issue.field_name}): ${issue.reason}`
  );
}

export default function ImportPage() {
  const { account } = useAccount();
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [dragging, setDragging] = useState(false);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const canCommit = preview && !preview.errors.length && preview.status === "ready";
  const totalRows = useMemo(
    () => preview?.reports.reduce((total, report) => total + report.rows, 0) ?? 0,
    [preview],
  );

  function choose(next: FileList | null) {
    if (!next) return;
    setFiles(Array.from(next));
    setPreview(null);
    setError("");
  }

  function drop(event: DragEvent) {
    event.preventDefault();
    setDragging(false);
    choose(event.dataTransfer.files);
  }

  async function analyze() {
    const body = new FormData();
    files.forEach((file) => body.append("files", file));
    setBusy(true);
    setError("");
    try {
      const query = account ? `?account_id=${account.id}` : "";
      setPreview(await api<Preview>(`/imports/preview${query}`, { method: "POST", body }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Import preview failed.");
    } finally {
      setBusy(false);
    }
  }

  async function commit() {
    if (!preview) return;
    setBusy(true);
    setError("");
    try {
      const result = await api<{ created: { trades: number }; account_id?: string }>(
        `/imports/${preview.session_id}/commit`,
        { method: "POST" },
      );
      router.push(result.created.trades ? "/trades" : "/");
      router.refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Import commit failed.");
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="One atomic session"
        title="Import trading data."
        description="Choose all related Tradovate reports together. JournalMe recognizes them by their contents, not their filenames."
      />
      {error && <ErrorState message={error} />}
      {!preview ? (
        <section className="import-card card">
          <button
            type="button"
            className={`drop-zone ${dragging ? "dragging" : ""}`}
            onClick={() => input.current?.click()}
            onDragEnter={() => setDragging(true)}
            onDragLeave={() => setDragging(false)}
            onDragOver={(event) => event.preventDefault()}
            onDrop={drop}
          >
            <span className="drop-icon"><Icon name="import" /></span>
            <strong>Drop your Tradovate reports here</strong>
            <span>or choose multiple CSV files from this device</span>
            <small>Performance, positions, fills, orders, cash, and balances · 10 MB each</small>
          </button>
          <input
            ref={input}
            type="file"
            accept=".csv,text/csv"
            multiple
            hidden
            onChange={(event) => choose(event.target.files)}
          />
          {!!files.length && (
            <div className="selected-files">
              <div>
                <strong>{files.length} report{files.length === 1 ? "" : "s"} selected</strong>
                <span>{files.map((file) => file.name).join(", ")}</span>
              </div>
              <button className="button primary" onClick={analyze} disabled={busy}>
                {busy ? "Reading reports..." : "Review import"}
              </button>
            </div>
          )}
          <div className="import-promise">
            <div><span>Read</span><p><strong>Recognize</strong>Reports are detected from verified headers.</p></div>
            <div><span>Match</span><p><strong>Reconcile</strong>Fills connect trades, orders, fees, and balances.</p></div>
            <div><span>Review</span><p><strong>Confirm</strong>Nothing is committed before you approve.</p></div>
          </div>
        </section>
      ) : (
        <section className="preview-layout">
          <article className="card preview-main">
            <div className="preview-title">
              <div>
                <p className="eyebrow">Ready to reconcile</p>
                <h2>{preview.new_trades} new canonical trades</h2>
              </div>
              <span>{totalRows} source rows</span>
            </div>
            <div className="report-list">
              {preview.reports.map((report) => (
                <div key={`${report.filename}-${report.type}`}>
                  <span className={`report-status ${report.status}`} />
                  <div>
                    <strong>{report.type.replaceAll("_", " ")}</strong>
                    <small>{report.filename}</small>
                  </div>
                  <span>{report.rows} rows</span>
                </div>
              ))}
            </div>
            {!!preview.warnings.length && (
              <div className="notice warning">
                {preview.warnings.map((warning) => <p key={warning}>{warning}</p>)}
              </div>
            )}
            {!!preview.errors.length && (
              <ErrorState message={preview.errors.map(issueMessage).join(" ")} />
            )}
          </article>
          <aside className="card preview-summary">
            <p className="eyebrow">Import summary</p>
            <dl>
              <div><dt>Coverage</dt><dd>{preview.coverage.start ?? "Unknown"} to {preview.coverage.end ?? "Unknown"}</dd></div>
              <div><dt>Source account</dt><dd>{preview.detected_accounts[0] ?? "Not detected"}</dd></div>
              <div><dt>Canonical trades</dt><dd>{preview.canonical_trades}</dd></div>
              <div><dt>Already imported</dt><dd>{preview.existing_trades}</dd></div>
              <div><dt>Open / unmatched fills</dt><dd>{preview.unmatched_fills}</dd></div>
              <div><dt>Linked filled orders</dt><dd>{preview.linked_filled_orders}</dd></div>
              <div><dt>Canceled/unfilled retained</dt><dd>{preview.canceled_unfilled_orders}</dd></div>
              <div><dt>Unmatched filled orders</dt><dd>{preview.unmatched_filled_orders}</dd></div>
              <div><dt>Duplicate rows</dt><dd>{preview.duplicate_rows}</dd></div>
            </dl>
            <button className="button primary" onClick={commit} disabled={!canCommit || busy}>
              {busy ? "Committing…" : "Confirm atomic import"}
            </button>
            <button className="button" onClick={() => setPreview(null)} disabled={busy}>
              Choose different files
            </button>
            <small>Fatal errors roll back the entire session.</small>
          </aside>
        </section>
      )}
    </>
  );
}
