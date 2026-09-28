"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { useAccount } from "@/components/account-provider";
import { ErrorState, PageHeader, Skeleton } from "@/components/ui";
import { API_BASE_URL, api, dateTime } from "@/lib/api";
import styles from "./connections.module.css";

type BrokerConnection = {
  id: string;
  account_id: string | null;
  provider: string;
  connection_type: string;
  display_name: string;
  status: string;
  external_account_id: string | null;
  metadata_json: Record<string, unknown>;
  bridge_key_configured: boolean;
  bridge_token_prefix: string | null;
  bridge_token_created_at: string | null;
  last_seen_at: string | null;
  last_sync_at: string | null;
};

type IssuedBridgeToken = {
  connection_id: string;
  bridge_token: string;
  bridge_token_prefix: string;
  created_at: string;
};

function timeLabel(value: string | null) {
  return value ? dateTime(value) : "Never";
}

export default function ConnectionsPage() {
  const { account, accounts } = useAccount();
  const [connections, setConnections] = useState<BrokerConnection[]>([]);
  const [issued, setIssued] = useState<IssuedBridgeToken | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [bridgeAccountName, setBridgeAccountName] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    return api<BrokerConnection[]>("/broker-connections", { cache: "reload" })
      .then((items) => {
        setConnections(items);
        setError("");
      })
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function createNinjaTraderSlot() {
    if (!account) return;
    setBusy("create");
    setError("");
    try {
      await api("/broker-connections", {
        method: "POST",
        body: JSON.stringify({
          provider: "ninjatrader",
          connection_type: "desktop_bridge",
          display_name: `NinjaTrader · ${account.name}`,
          account_id: account.id,
          external_account_id: account.external_account_id,
          metadata_json: { mode: "read_only", stage: "bridge", bridge_version: "0.7.1" },
        }),
      });
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Connection could not be created.");
    } finally {
      setBusy(null);
    }
  }

  async function issueBridgeKey(connection: BrokerConnection) {
    setBusy(connection.id);
    setIssued(null);
    setCopied(false);
    setError("");
    try {
      const result = await api<IssuedBridgeToken>(`/broker-connections/${connection.id}/bridge-token`, {
        method: "POST",
      });
      setIssued(result);
      setBridgeAccountName(connection.external_account_id ?? "");
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Bridge key could not be generated.");
    } finally {
      setBusy(null);
    }
  }

  async function revokeBridgeKey(connection: BrokerConnection) {
    setBusy(connection.id);
    setIssued(null);
    setCopied(false);
    setError("");
    try {
      await api(`/broker-connections/${connection.id}/bridge-token`, { method: "DELETE" });
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Bridge key could not be revoked.");
    } finally {
      setBusy(null);
    }
  }

  const issuedConnection = useMemo(
    () => connections.find((item) => item.id === issued?.connection_id) ?? null,
    [connections, issued],
  );

  const configText = issued && issuedConnection
    ? [
        `api_base=${API_BASE_URL}`,
        `bridge_token=${issued.bridge_token}`,
        `account_name=${bridgeAccountName || "REPLACE_WITH_NINJATRADER_ACCOUNT_NAME"}`,
      ].join("\n")
    : "";

  async function copyConfig() {
    if (!configText) return;
    await navigator.clipboard.writeText(configText);
    setCopied(true);
  }

  return (
    <div className="connections-page">
      <PageHeader
        eyebrow="Broker connections"
        title="One ingestion layer, multiple ways to sync"
        description="NinjaTrader is the live read-only desktop path. Tradovate catch-up and file import remain recovery paths when the desktop bridge was unavailable."
        action={account ? (
          <button className="button primary" type="button" disabled={busy !== null} onClick={() => void createNinjaTraderSlot()}>
            {busy === "create" ? "Creating…" : "Add NinjaTrader bridge"}
          </button>
        ) : undefined}
      />
      {error && <ErrorState message={error} />}

      <section className="connector-principles">
        <article className="card"><span>Live</span><h2>NinjaTrader bridge</h2><p>Executions sync automatically while NinjaTrader is running. The bridge cannot place or modify orders.</p></article>
        <article className="card"><span>Catch-up</span><h2>Tradovate</h2><p>Future browser or official connectivity can recover periods where the desktop bridge was unavailable.</p></article>
        <article className="card"><span>Fallback</span><h2>File import</h2><p>The existing importer remains the auditable historical and disaster-recovery path.</p></article>
      </section>

      {issued && issuedConnection && (
        <section className={`card ${styles.bridgeKeyCard}`}>
          <div className="section-title">
            <div>
              <p className="eyebrow">One-time setup</p>
              <h2>NinjaTrader bridge key generated</h2>
            </div>
          </div>
          <p className="muted">Save this locally on the NinjaTrader PC. JournalMe stores only a hash of the key, so this exact key will not be shown again after you leave this page.</p>
          <label className={styles.accountNameField}>
            <span>NinjaTrader account name</span>
            <input value={bridgeAccountName} onChange={(event) => setBridgeAccountName(event.target.value)} placeholder="Example: LFE05085094850003" />
            <small>Use the exact account name shown in NinjaTrader Control Center → Accounts.</small>
          </label>
          <pre className={styles.bridgeConfigPreview}>{configText}</pre>
          <div className="button-row">
            <button className="button primary" type="button" onClick={() => void copyConfig()}>{copied ? "Copied" : "Copy bridge config"}</button>
          </div>
          <p className="muted">Create <code>%USERPROFILE%\Documents\JournalMe\bridge.conf</code> and paste the copied contents there. Do not commit or share that file.</p>
        </section>
      )}

      {loading ? <Skeleton rows={4} /> : (
        <section className="card broker-connections-card">
          <div className="section-title"><div><p className="eyebrow">Registered connectors</p><h2>{connections.length ? `${connections.length} connection${connections.length === 1 ? "" : "s"}` : "No connectors registered yet"}</h2></div></div>
          {!connections.length ? <p className="muted">Create a NinjaTrader bridge for the selected account. The live bridge remains read-only and feeds the same JournalMe trade history as your other import paths.</p> : (
            <div className="broker-connection-list">
              {connections.map((item) => {
                const linked = accounts.find((candidate) => candidate.id === item.account_id);
                return (
                  <article key={item.id}>
                    <div>
                      <strong>{item.display_name}</strong>
                      <span>{item.provider} · {item.connection_type.replaceAll("_", " ")}</span>
                      {item.provider === "ninjatrader" && item.connection_type === "desktop_bridge" && (
                        <div className={styles.bridgeActions}>
                          <button className="button" type="button" disabled={busy === item.id} onClick={() => void issueBridgeKey(item)}>
                            {busy === item.id ? "Working…" : item.bridge_key_configured ? "Rotate bridge key" : "Generate bridge key"}
                          </button>
                          {item.bridge_key_configured && (
                            <button className="button quiet" type="button" disabled={busy === item.id} onClick={() => void revokeBridgeKey(item)}>Revoke</button>
                          )}
                          <small>{item.bridge_key_configured ? `Key configured · ${timeLabel(item.bridge_token_created_at)}` : "No bridge key yet"}</small>
                        </div>
                      )}
                    </div>
                    <div><span className={`connection-state ${item.status}`}>{item.status}</span><small>{linked?.name ?? "Unmapped account"}</small></div>
                    <div><span>Last seen</span><small>{timeLabel(item.last_seen_at)}</small></div>
                    <div><span>Last sync</span><small>{timeLabel(item.last_sync_at)}</small></div>
                  </article>
                );
              })}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
