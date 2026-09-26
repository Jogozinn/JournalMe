"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { useAccount } from "@/components/account-provider";
import { ErrorState, PageHeader, Skeleton } from "@/components/ui";
import { api, dateTime, money } from "@/lib/api";

type ImportSession = {
  id: string;
  account_id: string | null;
  status: string;
  started_at: string;
  committed_at: string | null;
  file_count: number;
  warnings: number;
  errors: number;
  filenames: string[];
  report_types: string[];
  summary: Record<string, unknown>;
};

type Quality = {
  unmatched_fills: number;
  unmatched_filled_orders: number;
  canceled_orders_retained: number;
  missing_commissions: number;
  reconciliation_warnings: unknown[];
  imported_balance: string | null;
  calculated_balance: string | null;
  balance_difference: string | null;
};

export default function ImportHistoryPage() {
  const { account } = useAccount();
  const [sessions, setSessions] = useState<ImportSession[]>([]);
  const [quality, setQuality] = useState<Quality | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const requests: [Promise<ImportSession[]>, Promise<Quality | null>] = [
      api<ImportSession[]>("/imports"),
      account ? api<Quality>(`/data-quality?account_id=${account.id}`) : Promise.resolve(null),
    ];
    Promise.all(requests)
      .then(([nextSessions, nextQuality]) => {
        setSessions(nextSessions);
        setQuality(nextQuality);
      })
      .catch((reason: Error) => setError(reason.message));
  }, [account]);
  return (
    <>
      <PageHeader eyebrow="Source ledger" title="Imports & data quality" description="Normal canceled orders remain retained evidence; only unmatched filled activity is treated as an error." action={<Link className="button primary" href="/import">New import</Link>} />
      {error && <ErrorState message={error} />}
      {quality && <section className="quality-grid">
        <article className="card"><span>Unmatched fills</span><strong>{quality.unmatched_fills}</strong><small>Should be zero</small></article>
        <article className="card"><span>Unmatched filled orders</span><strong>{quality.unmatched_filled_orders}</strong><small>Should be zero</small></article>
        <article className="card"><span>Canceled orders retained</span><strong>{quality.canceled_orders_retained}</strong><small>Normal source evidence</small></article>
        <article className="card"><span>Missing commissions</span><strong>{quality.missing_commissions}</strong><small>Unavailable, never assumed zero</small></article>
      </section>}
      {quality && <section className="card balance-check"><div><span>Imported balance</span><strong>{money(quality.imported_balance)}</strong></div><div><span>Starting balance + canonical net</span><strong>{money(quality.calculated_balance)}</strong></div><div><span>Difference</span><strong>{money(quality.balance_difference)}</strong></div></section>}
      {!sessions.length && !error ? <Skeleton rows={5} /> : <section className="import-history">
        {sessions.map((item) => <Link className="card import-history-row" href={`/imports/${item.id}`} key={item.id}>
          <div><strong>{dateTime(item.started_at)}</strong><span>{item.filenames.join(", ") || `${item.file_count} files`}</span></div>
          <div><span>Reports</span><strong>{item.report_types.map((value) => value.replaceAll("_", " ")).join(", ")}</strong></div>
          <div><span>Warnings</span><strong>{item.warnings}</strong></div>
          <div><span>Errors</span><strong>{item.errors}</strong></div>
          <span className={`status-text ${item.status === "committed" ? "complete" : "partial"}`}>{item.status}</span>
        </Link>)}
      </section>}
    </>
  );
}
