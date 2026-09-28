"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useAccount } from "@/components/account-provider";
import { api, money, price, quantity, timeOnly } from "@/lib/api";
import type { Trade } from "@/lib/types";

type BrokerConnection = {
  id: string;
  provider: string;
  display_name: string;
  status: string;
  last_seen_at: string | null;
  last_sync_at: string | null;
};

type BrokerActivityEvent = {
  id: string;
  connection_id: string;
  provider: string;
  external_execution_id: string;
  external_order_id: string | null;
  symbol: string;
  root_symbol: string;
  side: string;
  quantity: string;
  price: string;
  commission: string | null;
  currency: string;
  executed_at: string;
  ingest_status: string;
  market_position: string | null;
  completed_trade: Trade | null;
};

type BrokerActivityPayload = {
  connections: BrokerConnection[];
  events: BrokerActivityEvent[];
};

type LiveState = "live" | "retrying" | "error" | "offline";

const VISIBLE_POLL_INTERVAL_MS = 30_000;
const CLOCK_INTERVAL_MS = 15_000;

function relativeAge(value: string | null, now = Date.now()): string {
  if (!value) return "No recent event";
  const seconds = Math.max(0, Math.round((now - new Date(value).getTime()) / 1000));
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ago`;
}

function connectionState(connection: BrokerConnection | null, now = Date.now()): LiveState {
  if (!connection) return "offline";
  const status = connection.status.toLowerCase();
  if (status.includes("error") || status.includes("failed")) return "error";
  if (status.includes("retry") || status.includes("queue")) return "retrying";
  if (status !== "connected") return "offline";
  if (!connection.last_seen_at) return "offline";
  const staleMs = now - new Date(connection.last_seen_at).getTime();
  return staleMs <= 120_000 ? "live" : "offline";
}

function stateLabel(state: LiveState): string {
  if (state === "live") return "Live";
  if (state === "retrying") return "Retrying";
  if (state === "error") return "Error";
  return "Offline";
}

function eventTime(value: string): string {
  return timeOnly(value, { second: "2-digit" });
}

function EventSummary({ event, compact = false }: { event: BrokerActivityEvent; compact?: boolean }) {
  const trade = event.completed_trade;
  if (trade) {
    const pendingFees = trade.fees === null;
    const pnl = pendingFees ? trade.gross_pnl : trade.net_pnl;
    return (
      <>
        <strong>Trade completed</strong>
        <span>
          {trade.root_symbol ?? trade.symbol} · {trade.side} · {quantity(trade.quantity, true)}
        </span>
        {!compact && (
          <small>
            {money(pnl, trade.currency)} {pendingFees ? "gross · fees pending" : "net"} · {eventTime(event.executed_at)}
          </small>
        )}
      </>
    );
  }
  return (
    <>
      <strong>NinjaTrader synced</strong>
      <span>
        {event.side.toUpperCase()} {quantity(event.quantity)} {event.root_symbol || event.symbol} @ {price(event.price)}
      </span>
      {!compact && (
        <small>
          {event.market_position ? `Position: ${event.market_position} · ` : ""}
          {eventTime(event.executed_at)}
        </small>
      )}
    </>
  );
}

export function BrokerLiveActivity() {
  const { account } = useAccount();
  const [payload, setPayload] = useState<BrokerActivityPayload | null>(null);
  const [open, setOpen] = useState(false);
  const [toast, setToast] = useState<BrokerActivityEvent | null>(null);
  const [clock, setClock] = useState(Date.now());
  const seenIds = useRef<Set<string>>(new Set());
  const initialized = useRef(false);

  const refresh = useCallback(async () => {
    if (!account) return;
    try {
      const next = await api<BrokerActivityPayload>(
        `/broker-activity?account_id=${encodeURIComponent(account.id)}&limit=20`,
        { cache: "reload" },
      );
      setPayload(next);
      const currentIds = new Set(next.events.map((event) => event.id));
      if (!initialized.current) {
        seenIds.current = currentIds;
        initialized.current = true;
        return;
      }
      const newEvents = next.events.filter((event) => !seenIds.current.has(event.id));
      seenIds.current = currentIds;
      if (newEvents.length) setToast(newEvents[0]);
    } catch {
      // Connection state remains visible from the last successful poll. The
      // settings page owns detailed setup/errors; this control stays quiet.
    }
  }, [account]);

  useEffect(() => {
    initialized.current = false;
    seenIds.current = new Set();
    setPayload(null);
    setToast(null);
    setOpen(false);
    if (!account) return;

    const refreshWhenVisible = () => {
      if (document.visibilityState === "visible") void refresh();
    };

    // Trading activity is sparse, so avoid hammering the hosted API just to
    // keep the indicator fresh. Refresh immediately on entry/return, then at
    // a modest cadence only while JournalMe is actually visible.
    refreshWhenVisible();
    const timer = window.setInterval(refreshWhenVisible, VISIBLE_POLL_INTERVAL_MS);
    document.addEventListener("visibilitychange", refreshWhenVisible);
    window.addEventListener("focus", refreshWhenVisible);

    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
      window.removeEventListener("focus", refreshWhenVisible);
    };
  }, [account, refresh]);

  useEffect(() => {
    const timer = window.setInterval(() => setClock(Date.now()), CLOCK_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 7_000);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const connection = useMemo(() => {
    const connections = [...(payload?.connections ?? [])];
    connections.sort((left, right) => {
      const leftLive = left.status.toLowerCase() === "connected" ? 1 : 0;
      const rightLive = right.status.toLowerCase() === "connected" ? 1 : 0;
      if (leftLive !== rightLive) return rightLive - leftLive;
      const leftSeen = left.last_seen_at ? new Date(left.last_seen_at).getTime() : 0;
      const rightSeen = right.last_seen_at ? new Date(right.last_seen_at).getTime() : 0;
      return rightSeen - leftSeen;
    });
    return connections[0] ?? null;
  }, [payload]);
  const state = useMemo(() => connectionState(connection, clock), [connection, clock]);
  if (!account || !connection) return null;

  const latestAt = payload?.events[0]?.executed_at ?? connection.last_sync_at ?? connection.last_seen_at;

  return (
    <div className="broker-live-shell">
      {toast && (
        <div className="broker-live-toast" role="status" aria-live="polite">
          <button type="button" className="broker-live-toast-close" onClick={() => setToast(null)} aria-label="Dismiss sync notification">×</button>
          <EventSummary event={toast} />
          {toast.completed_trade && (
            <Link href={`/trades/${toast.completed_trade.id}`} onClick={() => setToast(null)}>View trade</Link>
          )}
        </div>
      )}

      {open && (
        <section className="broker-live-panel" aria-label="Recent NinjaTrader sync activity">
          <header>
            <div>
              <strong>Recent sync activity</strong>
              <small>NinjaTrader · {stateLabel(state)}</small>
            </div>
            <Link href="/settings/connections" onClick={() => setOpen(false)}>Connection settings</Link>
          </header>
          <div className="broker-live-events">
            {payload?.events.length ? payload.events.slice(0, 12).map((event) => (
              <div className="broker-live-event" key={event.id}>
                <span className="broker-live-event-dot" aria-hidden="true" />
                <div><EventSummary event={event} compact /></div>
                <time dateTime={event.executed_at}>{eventTime(event.executed_at)}</time>
              </div>
            )) : (
              <p className="muted small">Connected. Waiting for the next execution.</p>
            )}
          </div>
        </section>
      )}

      <button
        type="button"
        className={`broker-live-indicator ${state}`}
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        aria-label={`NinjaTrader ${stateLabel(state)}. Open recent sync activity.`}
      >
        <span className="broker-live-status-dot" aria-hidden="true" />
        <span><strong>NinjaTrader {stateLabel(state)}</strong><small>{relativeAge(latestAt, clock)}</small></span>
      </button>
    </div>
  );
}
