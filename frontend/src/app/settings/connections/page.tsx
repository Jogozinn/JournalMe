"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useAccount } from "@/components/account-provider";
import { ErrorState, Skeleton } from "@/components/ui";
import { API_BASE_URL, api } from "@/lib/api";
import styles from "./connections.module.css";

type Connection = {
  id: string; account_id: string | null; installation_id: string | null;
  provider: string; connection_type: string; display_name: string; status: string;
  source_namespace: string | null; source_account_name: string | null;
  bridge_key_configured: boolean; bridge_token_created_at: string | null;
  last_seen_at: string | null; last_sync_at: string | null;
  metadata_json: { pending_uploads?: number; legacy_pending_uploads?: number; last_failure_code?: string | null; last_failure_at?: string | null };
};
type Issued = { connection_id: string; bridge_token: string };
type ImportSession = { id: string; account_id: string | null; status: string; committed_at: string | null; warnings: number; summary: { preview?: { coverage?: { start: string | null; end: string | null } } } };
const time = (value: string | null) => value ? new Date(value).toLocaleString() : "Never";
function health(item: Connection) {
  if (item.status === "removed") return "Disconnected";
  if (item.status === "pending") return "Pending approval";
  if (!item.last_seen_at) return "Awaiting heartbeat";
  return Date.now() - new Date(item.last_seen_at).getTime() < 150_000 ? "Seen recently" : "Offline / stale";
}

export default function ConnectionsPage() {
  const { accounts, account } = useAccount();
  const [connections, setConnections] = useState<Connection[]>([]);
  const [issued, setIssued] = useState<Issued | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<Connection | null>(null);
  const [selected, setSelected] = useState<Record<string, string>>({});
  const [copied, setCopied] = useState(false);
  const [imports, setImports] = useState<ImportSession[]>([]);
  const load = useCallback(async () => {
    try { setConnections(await api<Connection[]>("/broker-connections", { cache: "reload" })); setError(""); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Connections could not be loaded."); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => {
    void load();
    const interval = window.setInterval(() => { void load(); }, 60_000);
    return () => window.clearInterval(interval);
  }, [load]);
  useEffect(() => { void api<ImportSession[]>("/imports").then(setImports).catch(() => setImports([])); }, []);
  const installations = useMemo(() => connections.filter(c => c.connection_type === "bridge_installation" && c.status !== "removed"), [connections]);
  const sources = useMemo(() => connections.filter(c => c.installation_id), [connections]);
  const other = useMemo(() => connections.filter(c => !c.installation_id && c.connection_type !== "bridge_installation"), [connections]);
  const config = issued ? `api_base=${API_BASE_URL}\nbridge_token=${issued.bridge_token}` : "";
  const latestReport = imports.find(item => item.status === "committed" && item.account_id === account?.id && item.summary?.preview?.coverage?.end);
  const selectedSources = sources.filter(item => item.account_id === account?.id && item.status !== "removed");
  const lastSeenForAccount = selectedSources.map(item => item.last_seen_at).filter((value): value is string => Boolean(value)).sort().at(-1) ?? null;

  async function createInstallation() {
    setBusy("new"); setError("");
    try {
      await api("/broker-connections", { method: "POST", body: JSON.stringify({ provider: "ninjatrader", connection_type: "bridge_installation", display_name: "NinjaTrader installation", metadata_json: { read_only: true } }) });
      await load();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Installation could not be created."); }
    finally { setBusy(null); }
  }
  async function issueKey(item: Connection) {
    setBusy(item.id); setIssued(null); setCopied(false); setError("");
    try { setIssued(await api<Issued>(`/broker-connections/${item.id}/bridge-token`, { method: "POST" })); await load(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Key could not be issued."); }
    finally { setBusy(null); }
  }
  async function authorize(item: Connection, accountId = selected[item.id]) {
    if (!accountId) return;
    setBusy(item.id); setError("");
    try { await api(`/broker-connections/${item.id}/authorize-source`, { method: "POST", body: JSON.stringify({ account_id: accountId }) }); await load(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Account could not be authorized."); }
    finally { setBusy(null); }
  }
  async function disconnect() {
    if (!confirm) return;
    const item = confirm; setBusy(item.id); setError("");
    try { await api(`/broker-connections/${item.id}/disconnect`, { method: "POST" }); if (issued?.connection_id === item.id) setIssued(null); setConfirm(null); await load(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Connection could not be disconnected."); }
    finally { setBusy(null); }
  }

  return <main className={styles.page}>
    <header className={styles.header}><p className="eyebrow">Settings / Data sources</p><h1>Broker Connections</h1><p>Connect one read-only NinjaTrader installation, then approve each detected source account for its own JournalMe trading account.</p></header>
    {error && <ErrorState message={error} />}
    {loading ? <Skeleton rows={4} /> : <>
      <section className={`card ${styles.section}`} aria-labelledby="bridge-title">
        <div className={styles.sectionHeader}><div><p className="eyebrow">Live capture</p><h2 id="bridge-title">NinjaTrader Bridge</h2></div><button className="button primary" onClick={() => void createInstallation()} disabled={busy !== null}>Add installation</button></div>
        <p className={styles.help}>Executions sync while NinjaTrader runs. Startup checks current-session executions only; it cannot recover older PC-off fills.</p>
        {!installations.length && <p className={styles.empty}>No installation paired yet. Add one, generate a key, and install the updated AddOn.</p>}
        {installations.map(item => {
          const children = sources.filter(source => source.installation_id === item.id);
          return <div className={styles.installation} key={item.id}>
            <div className={styles.sectionHeader}><div><strong>{item.display_name}</strong><span className={styles.id}>Installation {item.id.slice(0, 8)}</span></div><span className={styles.badge}>{health(item)}</span></div>
            <div className={styles.metrics}><div><span>Last bridge contact</span><strong>{time(item.last_seen_at)}</strong></div><div><span>Authorized accounts</span><strong>{children.filter(c => c.account_id && c.status !== "removed").length}</strong></div><div><span>Pending approval</span><strong>{children.filter(c => !c.account_id && c.status !== "removed").length}</strong></div><div><span>Queued uploads</span><strong>{item.metadata_json?.pending_uploads == null && item.metadata_json?.legacy_pending_uploads == null ? "Awaiting report" : (item.metadata_json?.pending_uploads ?? 0) + (item.metadata_json?.legacy_pending_uploads ?? 0)}</strong></div><div><span>Last fill sync</span><strong>{time(children.map(c => c.last_sync_at).filter(Boolean).sort().at(-1) ?? null)}</strong></div></div>
            <div className={styles.actions}><button className="button" disabled={busy !== null} onClick={() => void issueKey(item)}>{item.bridge_key_configured ? "Rotate key" : "Pair / generate key"}</button><button className="button quiet" disabled={busy !== null} onClick={() => setConfirm(item)}>Disconnect installation</button></div>
            <small className={styles.help}>Key {item.bridge_key_configured ? `configured ${time(item.bridge_token_created_at)}` : "not configured"}. Rotation immediately invalidates the previous key.</small>
            {item.metadata_json?.last_failure_code && <small className={styles.help}>Last upload failure: {item.metadata_json.last_failure_code} at {time(item.metadata_json.last_failure_at ?? null)}</small>}
          </div>;
        })}
      </section>
      {issued && <section className={`card ${styles.section}`} aria-label="One-time bridge key"><div className={styles.sectionHeader}><h2>Save this key now</h2><button className="button quiet" onClick={() => setIssued(null)}>Done</button></div><p className={styles.help}>Shown only now. Copy this configuration to <code>%USERPROFILE%\Documents\JournalMe\bridge.conf</code> on the NinjaTrader PC. Keep it private.</p><pre className={styles.config}>{config}</pre><button className="button primary" onClick={() => void navigator.clipboard.writeText(config).then(() => setCopied(true)).catch(() => setError("Clipboard access failed. Copy manually."))}>{copied ? "Copied" : "Copy configuration"}</button></section>}
      <section className={`card ${styles.section}`} aria-labelledby="accounts-title"><div className={styles.sectionHeader}><div><p className="eyebrow">Explicit authorization</p><h2 id="accounts-title">Detected NinjaTrader Accounts</h2></div><button className="button quiet" onClick={() => { setLoading(true); void load(); }}>Refresh</button></div>
        {!sources.length ? <p className={styles.empty}>Start NinjaTrader with the updated AddOn to detect connected accounts. New accounts remain pending until approved.</p> : <div className={styles.list}>{sources.map(item => <div className={styles.row} key={item.id}>
          <div><strong>{item.source_account_name}</strong><span className={styles.id}>{item.source_namespace} · {item.id.slice(0, 8)}</span></div>
          <div><span className={styles.badge}>{item.account_id ? health(item) : "Pending approval"}</span><small>Seen {time(item.last_seen_at)} · Fill {time(item.last_sync_at)}</small></div>
          <div className={styles.map}>{item.account_id ? <strong>{accounts.find(a => a.id === item.account_id)?.name ?? "Account unavailable"}</strong> : <><select aria-label={`JournalMe destination for ${item.source_account_name}`} value={selected[item.id] ?? ""} onChange={e => setSelected({ ...selected, [item.id]: e.target.value })}><option value="">Choose JournalMe account</option>{accounts.map(a => <option value={a.id} key={a.id}>{a.name}</option>)}</select><button className="button" disabled={!selected[item.id] || busy !== null} onClick={() => void authorize(item)}>Authorize</button></>}{item.status === "removed" && item.account_id ? <button className="button" disabled={busy !== null} onClick={() => void authorize(item, item.account_id!)}>Reconnect</button> : <button className="button quiet" disabled={busy !== null} onClick={() => setConfirm(item)}>Disconnect</button>}</div>
        </div>)}</div>}
      </section>
      <section className={`card ${styles.section}`}><p className="eyebrow">Recovery / Catch-up</p><h2>Historical catch-up not connected</h2><p className={styles.help}>Gap possible when NinjaTrader or this PC was off. Current-session replay and queued uploads cover only executions the AddOn actually observed. No verified Lucid historical API is connected.</p><p className={styles.help}>{selectedSources.length ? `For ${account?.name}, the last bridge observation was ${time(lastSeenForAccount)}. Any period after that observation is unverified until compared with broker records.` : `No authorized bridge source recorded for ${account?.name ?? "the selected account"}.`}</p><p className={styles.help}>{latestReport ? `Latest committed report for ${account?.name}: ${latestReport.summary.preview?.coverage?.start ?? "unknown"} to ${latestReport.summary.preview?.coverage?.end ?? "unknown"}; committed ${time(latestReport.committed_at)} with ${latestReport.warnings} warning(s). This is report evidence, not proof of complete history.` : `No committed report coverage recorded for ${account?.name ?? "the selected account"}.`}</p><div className={styles.actions}><Link className="button primary" href="/import">Import a broker report</Link><Link className="button" href="/imports">Review import coverage</Link></div><p className={styles.help}>For missing dates, obtain a Tradovate-style broker report or official statement supported by Imports. NinjaTrader&apos;s Control Center Executions CSV covers the current day and its generic format is not supported here.</p></section>
      <section className={`card ${styles.section}`}><p className="eyebrow">Registered connectors</p><h2>Connections and history</h2><p className={styles.help}>Repeated names are separate records. Check the short ID, destination and last sync before disconnecting an old connector.</p>{!other.length ? <p className={styles.empty}>No other connectors registered.</p> : <div className={styles.list}>{other.map(item => <div className={styles.row} key={item.id}><div><strong>{item.display_name}</strong><span className={styles.id}>{item.provider} · {item.connection_type.replaceAll("_", " ")} · {item.id.slice(0, 8)}</span></div><div><span className={styles.badge}>{health(item)}</span><small>Seen {time(item.last_seen_at)} · Synced {time(item.last_sync_at)}</small></div><div className={styles.map}><strong>{accounts.find(a => a.id === item.account_id)?.name ?? "Unmapped"}</strong>{item.status !== "removed" && <button className="button quiet" disabled={busy !== null} onClick={() => setConfirm(item)}>Disconnect</button>}</div></div>)}</div>}</section>
      <section className={`card ${styles.section}`}><p className="eyebrow">Other sources</p><h2>File import and Tradovate</h2><p className={styles.help}>Tradovate-style report import is available for historical dates. Direct Tradovate API catch-up is not connected and requires provider eligibility.</p><Link className="button" href="/import">Open file import</Link></section>
      <section className={`card ${styles.section}`}><p className="eyebrow">Separate capture tool</p><h2>Chrome Companion</h2><p className={styles.help}>Capture and review context from Chrome. The Companion does not supply NinjaTrader execution history.</p><a className="button" href="/downloads/JournalMe_Companion_v0.8.2.zip" download>Download Companion</a></section>
    </>}
    {confirm && <div className={styles.dialogBackdrop} role="presentation"><div className={styles.dialog} role="dialog" aria-modal="true" aria-labelledby="disconnect-title"><h2 id="disconnect-title">Disconnect this connector?</h2><p>Its key will be revoked and future sync stopped. JournalMe trading accounts, past trades, screenshots, analyses, and learning data stay in place.</p><p className={styles.id}>{confirm.display_name} · {confirm.id.slice(0, 8)}</p><div className={styles.actions}><button className="button" onClick={() => setConfirm(null)}>Cancel</button><button className="button primary" disabled={busy !== null} onClick={() => void disconnect()}>{busy ? "Disconnecting…" : "Disconnect"}</button></div></div></div>}
  </main>;
}
