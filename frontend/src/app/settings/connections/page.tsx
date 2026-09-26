"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useAccount } from "@/components/account-provider";
import { ErrorState, PageHeader } from "@/components/ui";
import { api, dateTime } from "@/lib/api";
import {
  syncTradovateReports,
  tradovateHasBalanceReport,
  type BrokerSyncResult,
} from "@/lib/broker-sync";

type ImportHistoryItem = {
  id: string;
  status: string;
  started_at: string;
  committed_at: string | null;
  file_count: number;
  report_types: string[];
  summary: {
    commit?: {
      trades?: number;
      fills?: number;
      orders?: number;
      cash_transactions?: number;
      daily_balances?: number;
    };
  } | null;
};

function syncSummary(result: BrokerSyncResult): string {
  const parts = [
    `${result.created.trades} new trade${result.created.trades === 1 ? "" : "s"}`,
    `${result.created.fills} fill${result.created.fills === 1 ? "" : "s"}`,
  ];
  if (result.created.daily_balances) {
    parts.push(`${result.created.daily_balances} balance snapshot${result.created.daily_balances === 1 ? "" : "s"}`);
  }
  return parts.join(" · ");
}

export default function BrokerConnectionsPage() {
  const { account, refresh } = useAccount();
  const picker = useRef<HTMLInputElement>(null);
  const [history, setHistory] = useState<ImportHistoryItem[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<BrokerSyncResult | null>(null);

  const loadHistory = useCallback(async () => {
    try {
      setHistory(await api<ImportHistoryItem[]>("/imports", { cache: "reload" }));
    } catch {
      // Import history is supporting context only. Sync still remains available.
    }
  }, []);

  useEffect(() => {
    void loadHistory();
  }, [loadHistory]);

  const lastSync = useMemo(
    () => history.find((item) => item.status === "committed" && item.report_types.some((type) => ["performance", "position_history", "fills"].includes(type))),
    [history],
  );

  async function choose(files: FileList | null) {
    if (!files?.length) return;
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const synced = await syncTradovateReports(Array.from(files), account?.id ?? null);
      setResult(synced);
      await Promise.all([refresh(), loadHistory()]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Tradovate sync could not be completed.");
    } finally {
      setBusy(false);
      if (picker.current) picker.current.value = "";
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Broker connections"
        title="Keep JournalMe current."
        description="Sync execution history without rebuilding your journal workflow every time you trade."
        action={<Link className="button" href="/imports">Import history</Link>}
      />
      {error && <ErrorState message={error} />}

      <section className="broker-connection-grid">
        <article className="card broker-connection-card featured">
          <div className="broker-card-head">
            <div>
              <span className="broker-provider-mark">TV</span>
              <div>
                <p className="eyebrow">Tradovate</p>
                <h2>Report Sync</h2>
              </div>
            </div>
            <span className="connection-badge ready">Ready</span>
          </div>

          <p className="broker-copy">
            Your Lucid/Tradovate account does not need API credentials for this mode. Download the latest reports, press Sync now, and JournalMe recognizes, deduplicates, and commits them automatically.
          </p>

          <div className="broker-sync-requirements">
            <div><strong>Core</strong><span>Performance + Fills</span></div>
            <div><strong>Recommended</strong><span>Account Balance History</span></div>
            <div><strong>Optional</strong><span>Orders, Cash History, Position History</span></div>
          </div>

          <div className="broker-status-strip">
            <div>
              <span>Account</span>
              <strong>{account?.name ?? "Choose or create a JournalMe account"}</strong>
            </div>
            <div>
              <span>Last synced</span>
              <strong>{lastSync?.committed_at ? dateTime(lastSync.committed_at) : "Not synced yet"}</strong>
            </div>
            <div>
              <span>Connection</span>
              <strong>Secure report import</strong>
            </div>
          </div>

          {result && (
            <div className="broker-sync-result" role="status">
              <strong>Sync complete</strong>
              <span>{syncSummary(result)}</span>
              {!tradovateHasBalanceReport(result.preview) && (
                <small>Trades are current. Add Account Balance History next time if you want the broker balance snapshot refreshed too.</small>
              )}
            </div>
          )}

          <div className="broker-actions">
            <button className="button primary" type="button" disabled={busy} onClick={() => picker.current?.click()}>
              {busy ? "Syncing…" : "Sync now"}
            </button>
            <Link className="button" href="/import">Use full import review</Link>
          </div>
          <input
            ref={picker}
            type="file"
            accept=".csv,text/csv"
            multiple
            hidden
            onChange={(event) => void choose(event.target.files)}
          />
          <small className="broker-security-note">JournalMe never asks for or stores your Tradovate password in Report Sync mode.</small>
        </article>

        <article className="card broker-connection-card">
          <div className="broker-card-head">
            <div>
              <span className="broker-provider-mark muted-mark">API</span>
              <div>
                <p className="eyebrow">Future connector</p>
                <h2>Official API Sync</h2>
              </div>
            </div>
            <span className="connection-badge">Not configured</span>
          </div>
          <p className="broker-copy">If a broker account provides official API or OAuth access, JournalMe can use the same normalized trade pipeline for one-click or automatic synchronization.</p>
          <div className="broker-roadmap">
            <span>Connect once</span><span>Sync new fills</span><span>Deduplicate</span><span>Update JournalMe</span>
          </div>
        </article>
      </section>
    </>
  );
}
