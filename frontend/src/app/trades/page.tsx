"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { useAccount } from "@/components/account-provider";
import { EmptyState, ErrorState, PageHeader, Pnl, Skeleton } from "@/components/ui";
import { api, dateTime, duration, money, quantity } from "@/lib/api";
import type { Trade } from "@/lib/types";


function displayedPnl(trade: Trade): string {
  return trade.fees === null ? trade.gross_pnl : trade.net_pnl;
}

function pnlLabel(trade: Trade): string {
  return trade.fees === null ? "Gross P&L" : "Net P&L";
}

export default function TradesPage() {
  const { account, loading } = useAccount();
  const [trades, setTrades] = useState<Trade[]>([]);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState("");
  const [result, setResult] = useState("");
  const [error, setError] = useState("");
  const [fetching, setFetching] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);

  useEffect(() => {
    if (!account) return;
    setFetching(true);
    const params = new URLSearchParams({ account_id: account.id });
    if (search) params.set("search", search);
    if (result) params.set("result", result);
    const timer = window.setTimeout(() => {
      api<{ items: Trade[]; total: number }>(`/trades?${params}`)
        .then((payload) => {
          setTrades(payload.items);
          setTotal(payload.total);
          setError("");
          setSelectedIndex(null);
        })
        .catch((reason: Error) => setError(reason.message))
        .finally(() => setFetching(false));
    }, 120);
    return () => window.clearTimeout(timer);
  }, [account, search, result]);

  const selectedTrade = useMemo(
    () => selectedIndex === null ? null : trades[selectedIndex] ?? null,
    [selectedIndex, trades],
  );

  useEffect(() => {
    if (selectedIndex === null) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSelectedIndex(null);
      if (event.key === "ArrowDown" || event.key === "ArrowRight") {
        event.preventDefault();
        setSelectedIndex((value) => Math.min((value ?? 0) + 1, trades.length - 1));
      }
      if (event.key === "ArrowUp" || event.key === "ArrowLeft") {
        event.preventDefault();
        setSelectedIndex((value) => Math.max((value ?? 0) - 1, 0));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selectedIndex, trades.length]);

  if (loading) return <Skeleton rows={5} />;
  if (!account) {
    return <EmptyState title="Create an account first." copy="Your trades belong to a trading account." href="/" action="Set up account" />;
  }

  return (
    <>
      <PageHeader
        eyebrow={`${total} normalized trades`}
        title="Trades"
        description="Scan the executions. Open the ones that deserve a closer look."
      />
      <div className="trade-filters premium-filter-bar">
        <input
          className="filter-input"
          type="search"
          placeholder="Search symbol"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <select
          className="filter-input"
          value={result}
          onChange={(event) => setResult(event.target.value)}
          aria-label="Filter by result"
        >
          <option value="">All results</option>
          <option value="winner">Winners</option>
          <option value="loser">Losers</option>
          <option value="breakeven">Breakeven</option>
        </select>
        <span className="filter-status">{fetching ? "Refreshing" : `${trades.length} shown`}</span>
      </div>
      {error && <ErrorState message={error} />}
      {fetching && !trades.length ? (
        <Skeleton rows={5} />
      ) : !trades.length ? (
        <EmptyState
          title={search || result ? "No trades match these filters." : "No trades imported yet."}
          copy={search || result ? "Adjust the symbol or result filter." : "Import trading data to build your review queue."}
        />
      ) : (
        <>
          <section className="trade-table card premium-trade-table">
            <div className="trade-row trade-head">
              <span>Trade</span><span>Entry</span><span>Side</span><span>Size</span><span>Duration</span><span>P&L</span>
            </div>
            {trades.map((trade, index) => (
              <button className="trade-row trade-row-button" type="button" onClick={() => setSelectedIndex(index)} key={trade.id}>
                <span><strong>{trade.symbol}</strong><small>{trade.source === "manual" ? "Manual source" : trade.journaled ? "Journal started" : "Needs review"}</small></span>
                <span>{new Date(trade.entry_timestamp).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</span>
                <span><i className={`side-token ${trade.side}`}>{trade.side}</i></span>
                <span className="mono">{quantity(trade.quantity)}</span>
                <span>{duration(trade.duration_seconds)}</span>
                <span className="trade-pnl-cell"><Pnl value={displayedPnl(trade)}>{money(displayedPnl(trade))}</Pnl>{trade.fees === null && <small>fees pending</small>}</span>
              </button>
            ))}
          </section>
          <section className="trade-cards">
            {trades.map((trade, index) => (
              <button className="trade-card card" type="button" onClick={() => setSelectedIndex(index)} key={trade.id}>
                <div><span className={`side-token ${trade.side}`}>{trade.side}</span><small>{new Date(trade.entry_timestamp).toLocaleDateString()}</small></div>
                <h2>{trade.symbol}</h2>
                <dl>
                  <div><dt>Quantity</dt><dd>{quantity(trade.quantity)}</dd></div>
                  <div><dt>Duration</dt><dd>{duration(trade.duration_seconds)}</dd></div>
                  <div><dt>{pnlLabel(trade)}</dt><dd><Pnl value={displayedPnl(trade)}>{money(displayedPnl(trade))}</Pnl>{trade.fees === null && <small className="fees-pending">fees pending</small>}</dd></div>
                </dl>
              </button>
            ))}
          </section>
        </>
      )}

      {selectedTrade && selectedIndex !== null && (
        <div className="trade-lens-backdrop" role="presentation" onMouseDown={() => setSelectedIndex(null)}>
          <aside className="trade-lens" role="dialog" aria-modal="true" aria-label={`${selectedTrade.symbol} trade lens`} onMouseDown={(event) => event.stopPropagation()}>
            <header>
              <div>
                <p className="eyebrow">Trade lens</p>
                <div className="trade-lens-title"><h2>{selectedTrade.symbol}</h2><span className={`side-token ${selectedTrade.side}`}>{selectedTrade.side}</span></div>
                <p>{dateTime(selectedTrade.entry_timestamp)}</p>
              </div>
              <button className="icon-button" type="button" onClick={() => setSelectedIndex(null)} aria-label="Close trade lens">×</button>
            </header>
            <div className="trade-lens-pnl">
              <span>{pnlLabel(selectedTrade)}</span>
              <Pnl value={displayedPnl(selectedTrade)}>{money(displayedPnl(selectedTrade))}</Pnl>
              {selectedTrade.fees === null && <small className="fees-pending">Fees pending from broker import</small>}
            </div>
            <dl className="trade-lens-stats">
              <div><dt>Size</dt><dd>{quantity(selectedTrade.quantity, true)}</dd></div>
              <div><dt>Duration</dt><dd>{duration(selectedTrade.duration_seconds)}</dd></div>
              <div><dt>Source</dt><dd>{selectedTrade.source === "manual" ? "Manual" : "Imported"}</dd></div>
              <div><dt>Journal</dt><dd>{selectedTrade.journaled ? "Started" : "Needs review"}</dd></div>
            </dl>
            <div className="trade-lens-actions">
              <Link className="button primary" href={`/trades/${selectedTrade.id}`}>Open full review</Link>
              <Link className="button" href={`/timeline/${selectedTrade.entry_timestamp.slice(0, 10)}`}>Open trading day</Link>
            </div>
            <footer>
              <button type="button" disabled={selectedIndex === 0} onClick={() => setSelectedIndex(Math.max(selectedIndex - 1, 0))}>← Previous</button>
              <span>{selectedIndex + 1} of {trades.length}</span>
              <button type="button" disabled={selectedIndex >= trades.length - 1} onClick={() => setSelectedIndex(Math.min(selectedIndex + 1, trades.length - 1))}>Next →</button>
            </footer>
          </aside>
        </div>
      )}
    </>
  );
}
