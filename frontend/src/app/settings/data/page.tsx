"use client";

import { useEffect, useState } from "react";

import { useAccount } from "@/components/account-provider";
import { AuthenticatedDownloadLink } from "@/components/authenticated-assets";
import { ErrorState, PageHeader, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";

type BackupStatus = {
  mode: string;
  database_location: string;
  attachment_location: string;
  account_count: number;
  export_schema_version: number;
  status: string;
  recommendation: string;
};

export default function DataSettingsPage() {
  const { account } = useAccount();
  const [status, setStatus] = useState<BackupStatus | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api<BackupStatus>("/backup-status")
      .then(setStatus)
      .catch((reason: Error) => setError(reason.message));
  }, []);
  return (
    <>
      <PageHeader eyebrow="Portable by design" title="Data & backups" description="Your records can leave JournalMe in documented, readable formats." />
      {error && <ErrorState message={error} />}
      <section className="export-grid">
        <article className="card export-card"><p className="eyebrow">Current account</p><h2>Trades CSV</h2><p>Canonical and manual trade facts with Decimal values and visible source labels.</p><AuthenticatedDownloadLink className="button primary" disabled={!account} path={account ? `/exports/trades.csv?account_id=${account.id}` : ""} filename="journalme-trades.csv">Export trades</AuthenticatedDownloadLink></article>
        <article className="card export-card"><p className="eyebrow">Current account</p><h2>Journals JSON</h2><p>Trade journals and daily reviews with a versioned export envelope.</p><AuthenticatedDownloadLink className="button primary" disabled={!account} path={account ? `/exports/journals.json?account_id=${account.id}` : ""} filename="journalme-journals.json">Export journals</AuthenticatedDownloadLink></article>
        <article className="card export-card"><p className="eyebrow">All user data</p><h2>Complete ZIP archive</h2><p>Accounts, trades, journals, playbooks, reviews, goals, audit events, and attachments.</p><AuthenticatedDownloadLink className="button primary" path="/exports/archive.zip" filename="journalme-backup.zip">Export full backup</AuthenticatedDownloadLink></article>
      </section>
      {!status ? <Skeleton rows={4} /> : <section className="card backup-card">
        <div className="section-title"><div><p className="eyebrow">{status.mode} backup status</p><h2>{status.status === "ready" ? "Ready to back up" : status.status}</h2></div><span>Schema v{status.export_schema_version}</span></div>
        <dl><div><dt>Database</dt><dd>{status.database_location}</dd></div><div><dt>Attachments</dt><dd>{status.attachment_location}</dd></div><div><dt>Accounts</dt><dd>{status.account_count}</dd></div></dl>
        <p>{status.recommendation} Stop the local API before copying the database and storage directory, then restore both together.</p>
      </section>}
      <section className="card danger-zone"><p className="eyebrow">Destructive actions</p><h2>Reset is intentionally unavailable in the browser</h2><p>A complete reset can orphan broker evidence if interrupted. Export a full archive first; use a future staged restore/reset workflow rather than a one-click delete.</p></section>
    </>
  );
}
