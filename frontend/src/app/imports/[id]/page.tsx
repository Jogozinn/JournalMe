"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

import { ErrorState, PageHeader, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";

type Detail = {
  id: string;
  status: string;
  files: {
    id: string;
    filename: string;
    type: string;
    rows: number;
    valid_rows: number;
    duplicate_rows: number;
    error_rows: number;
    status: string;
    content_hash: string;
    header_signature: string;
  }[];
  summary: {
    preview?: {
      coverage?: { start: string | null; end: string | null };
      canonical_trades?: number;
      new_trades?: number;
      existing_trades?: number;
      unmatched_fills?: number;
      linked_filled_orders?: number;
      canceled_unfilled_orders?: number;
      unmatched_filled_orders?: number;
      warnings?: string[];
    };
    committed?: Record<string, number>;
  };
};

export default function ImportDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<Detail | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api<Detail>(`/imports/${id}`).then(setData).catch((reason: Error) => setError(reason.message));
  }, [id]);
  if (!data) return error ? <ErrorState message={error} /> : <Skeleton rows={7} />;
  const preview = data.summary.preview ?? {};
  return (
    <>
      <PageHeader eyebrow={`Import session · ${data.status}`} title="Source and reconciliation detail" description={`${preview.coverage?.start ?? "Unknown"} to ${preview.coverage?.end ?? "Unknown"} coverage`} action={<Link className="button" href="/imports">Import history</Link>} />
      <section className="quality-grid">
        <article className="card"><span>Canonical trades</span><strong>{preview.canonical_trades ?? "Not available"}</strong><small>{preview.new_trades ?? 0} new · {preview.existing_trades ?? 0} existing</small></article>
        <article className="card"><span>Linked filled orders</span><strong>{preview.linked_filled_orders ?? "Not available"}</strong><small>Matched to fill evidence</small></article>
        <article className="card"><span>Canceled retained</span><strong>{preview.canceled_unfilled_orders ?? "Not available"}</strong><small>Not an error</small></article>
        <article className="card"><span>Unmatched filled orders</span><strong>{preview.unmatched_filled_orders ?? "Not available"}</strong><small>Requires attention if non-zero</small></article>
      </section>
      {!!preview.warnings?.length && <div className="notice warning">{preview.warnings.map((warning) => <p key={warning}>{warning}</p>)}</div>}
      <section className="card file-audit">
        <div className="file-audit-row file-audit-head"><span>File / report</span><span>Rows</span><span>Valid</span><span>Duplicates</span><span>Errors</span><span>Status</span></div>
        {data.files.map((file) => <div className="file-audit-row" key={file.id}><span><strong>{file.filename}</strong><small>{file.type.replaceAll("_", " ")}</small><code title={file.content_hash}>{file.content_hash.slice(0, 12)}…</code></span><span>{file.rows}</span><span>{file.valid_rows}</span><span>{file.duplicate_rows}</span><span>{file.error_rows}</span><span>{file.status}</span></div>)}
      </section>
    </>
  );
}
