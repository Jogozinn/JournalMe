"use client";

import { useCallback, useEffect, useState } from "react";

import { useAccount } from "@/components/account-provider";
import { ErrorState, PageHeader, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";

type BrokerConnection = {
  id: string;
  account_id: string | null;
  provider: string;
  connection_type: string;
  display_name: string;
  status: string;
  external_account_id: string | null;
  metadata_json: Record<string, unknown>;
  last_seen_at: string | null;
  last_sync_at: string | null;
};

function timeLabel(value: string | null) {
  return value ? new Date(value).toLocaleString() : "Never";
}

export default function ConnectionsPage() {
  const { account, accounts } = useAccount();
  const [connections, setConnections] = useState<BrokerConnection[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    return api<BrokerConnection[]>("/broker-connections")
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
    setCreating(true);
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
          metadata_json: { mode: "read_only", stage: "probe" },
        }),
      });
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Connection slot could not be created.");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="connections-page">
      <PageHeader
        eyebrow="Broker connections"
        title="One ingestion layer, multiple ways to sync"
        description="NinjaTrader can become the live desktop path, Tradovate can provide catch-up, and CSV remains the recovery path. All connectors feed the same JournalMe history."
        action={account ? <button className="button primary" type="button" disabled={creating} onClick={() => void createNinjaTraderSlot()}>{creating ? "Creating…" : "Add NinjaTrader probe"}</button> : undefined}
      />
      {error && <ErrorState message={error} />}
      <section className="connector-principles">
        <article className="card"><span>Live</span><h2>NinjaTrader bridge</h2><p>Read-only execution and account events while NinjaTrader is running.</p></article>
        <article className="card"><span>Catch-up</span><h2>Tradovate</h2><p>Browser-session or report-assisted recovery for periods where the desktop bridge was unavailable.</p></article>
        <article className="card"><span>Fallback</span><h2>File import</h2><p>The existing importer remains the auditable historical and disaster-recovery path.</p></article>
      </section>
      {loading ? <Skeleton rows={4} /> : (
        <section className="card broker-connections-card">
          <div className="section-title"><div><p className="eyebrow">Registered connectors</p><h2>{connections.length ? `${connections.length} connection${connections.length === 1 ? "" : "s"}` : "No connectors registered yet"}</h2></div></div>
          {!connections.length ? <p className="muted">Create a NinjaTrader probe slot for the selected account. The first bridge build will attach to this record without changing or placing any orders.</p> : (
            <div className="broker-connection-list">
              {connections.map((item) => {
                const linked = accounts.find((candidate) => candidate.id === item.account_id);
                return (
                  <article key={item.id}>
                    <div><strong>{item.display_name}</strong><span>{item.provider} · {item.connection_type.replaceAll("_", " ")}</span></div>
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
