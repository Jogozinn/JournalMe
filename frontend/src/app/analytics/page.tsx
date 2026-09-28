"use client";

import { useEffect, useMemo, useState } from "react";

import { useAccount } from "@/components/account-provider";
import { AuthenticatedDownloadLink } from "@/components/authenticated-assets";
import { EmptyState, ErrorState, PageHeader, Pnl, Skeleton } from "@/components/ui";
import { api, hourLabel12, money, percent } from "@/lib/api";
import type { Metrics } from "@/lib/types";

type Group = { label: string; net_pnl: string; trade_count: number; win_rate: string | null; expectancy: string | null };
type Analytics = {
  metrics: Metrics & {
    trade_count: number;
    max_drawdown: string;
    total_fees: string;
    fees_percent_of_gross: string | null;
    average_duration_seconds: number | null;
    winning_streak: number;
    losing_streak: number;
  };
  by_symbol: Group[];
  by_root_symbol: Group[];
  by_weekday: Group[];
  by_hour: Group[];
  by_side: Group[];
  by_grade: Group[];
  by_review_status: Group[];
  equity_and_drawdown: { at: string; net_pnl: string; drawdown: string }[];
};

function PerformanceTable({ title, rows }: { title: string; rows: Group[] }) {
  return (
    <article className="card analytics-table">
      <h2>{title}</h2>
      {rows.length ? rows.map((row) => (
        <div key={row.label}>
          <strong>{row.label}</strong>
          <span>{row.trade_count} trades</span>
          <span>{percent(row.win_rate)}</span>
          <Pnl value={row.net_pnl}>{money(row.net_pnl)}</Pnl>
        </div>
      )) : <p className="muted">Add more journal context to reveal this pattern.</p>}
    </article>
  );
}

function PerformanceBars({ title, eyebrow, rows, limit = 8 }: { title: string; eyebrow: string; rows: Group[]; limit?: number }) {
  const visible = rows.slice(0, limit);
  const maxAbs = Math.max(1, ...visible.map((row) => Math.abs(Number(row.net_pnl))));
  return (
    <article className="card performance-board">
      <div className="section-title">
        <div><p className="eyebrow">{eyebrow}</p><h2>{title}</h2></div>
      </div>
      <div className="performance-bars">
        {visible.length ? visible.map((row) => {
          const pnl = Number(row.net_pnl);
          const width = Math.max(4, Math.round((Math.abs(pnl) / maxAbs) * 100));
          return (
            <div className="performance-bar-row" key={row.label}>
              <div className="performance-bar-meta"><strong>{row.label}</strong><span>{row.trade_count} trades · {percent(row.win_rate)}</span></div>
              <div className="performance-track"><i className={pnl > 0 ? "gain" : pnl < 0 ? "loss" : "flat"} style={{ width: `${width}%` }} /></div>
              <Pnl value={row.net_pnl}>{money(row.net_pnl)}</Pnl>
            </div>
          );
        }) : <p className="muted">Not enough data yet.</p>}
      </div>
    </article>
  );
}

function extreme(rows: Group[], mode: "high" | "low") {
  if (!rows.length) return null;
  return rows.reduce((picked, row) => {
    const current = Number(row.net_pnl);
    const best = Number(picked.net_pnl);
    return mode === "high" ? (current > best ? row : picked) : (current < best ? row : picked);
  });
}

export default function AnalyticsPage() {
  const { account, loading } = useAccount();
  const [data, setData] = useState<Analytics | null>(null);
  const [error, setError] = useState("");
  const [symbol, setSymbol] = useState("");
  const [side, setSide] = useState("");
  const [reviewed, setReviewed] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const query = new URLSearchParams({ account_id: account?.id ?? "" });
  if (symbol) query.set("symbol", symbol);
  if (side) query.set("side", side);
  if (reviewed) query.set("reviewed_status", reviewed);
  if (start) query.set("start", start);
  if (end) query.set("end", end);

  useEffect(() => {
    if (!account) return;
    const params = new URLSearchParams({ account_id: account.id });
    if (symbol) params.set("symbol", symbol);
    if (side) params.set("side", side);
    if (reviewed) params.set("reviewed_status", reviewed);
    if (start) params.set("start", start);
    if (end) params.set("end", end);
    const timer = window.setTimeout(() => api<Analytics>(`/analytics/advanced?${params}`)
      .then((value) => {
        setData(value);
        setError("");
      })
      .catch((reason: Error) => setError(reason.message)), 120);
    return () => window.clearTimeout(timer);
  }, [account, end, reviewed, side, start, symbol]);

  const scan = useMemo(() => {
    if (!data) return [];
    const highDay = extreme(data.by_weekday, "high");
    const lowHour = extreme(data.by_hour, "low");
    const highSide = extreme(data.by_side, "high");
    return [
      highDay && { label: "Highest net weekday", value: highDay.label, detail: `${money(highDay.net_pnl)} across ${highDay.trade_count} trades`, tone: Number(highDay.net_pnl) >= 0 ? "positive" : "negative" },
      lowHour && { label: "Lowest net entry hour", value: hourLabel12(lowHour.label), detail: `${money(lowHour.net_pnl)} across ${lowHour.trade_count} trades`, tone: Number(lowHour.net_pnl) >= 0 ? "positive" : "negative" },
      highSide && { label: "Higher net side", value: highSide.label, detail: `${money(highSide.net_pnl)} · ${percent(highSide.win_rate)} win rate`, tone: Number(highSide.net_pnl) >= 0 ? "positive" : "negative" },
    ].filter(Boolean) as { label: string; value: string; detail: string; tone: string }[];
  }, [data]);

  if (loading) return <Skeleton rows={5} />;
  if (!account) return <EmptyState title="Create an account first." copy="Analytics always respect the selected account." href="/" action="Set up account" />;
  if (error) return <ErrorState message={error} />;
  if (!data) return <Skeleton rows={5} />;
  if (!data.metrics.trade_count) return <EmptyState title="Patterns need real trades." copy="Import trading data, then use manual setup and mistake tags to make the analysis personal." />;

  return (
    <>
      <PageHeader eyebrow="Pattern scan" title="Analytics" description="Find where the results are coming from without hiding the sample size." />
      <section className="analytics-filters card premium-filter-bar analytics-filter-bar">
        <input aria-label="Filter symbol" type="search" placeholder="Filter symbol" value={symbol} onChange={(event) => setSymbol(event.target.value)} />
        <select aria-label="Side" value={side} onChange={(event) => setSide(event.target.value)}><option value="">Long and short</option><option value="long">Long</option><option value="short">Short</option></select>
        <select aria-label="Review state" value={reviewed} onChange={(event) => setReviewed(event.target.value)}><option value="">All review states</option><option value="unreviewed">Unreviewed</option><option value="partial">Partial</option><option value="complete">Complete</option></select>
        <input aria-label="Start date" type="date" value={start} max={end || undefined} onChange={(event) => setStart(event.target.value)} />
        <input aria-label="End date" type="date" value={end} min={start || undefined} onChange={(event) => setEnd(event.target.value)} />
        <AuthenticatedDownloadLink path={`/exports/analytics.csv?${query}`} filename="journalme-analytics.csv">Export CSV</AuthenticatedDownloadLink>
        <span>Account · {account.name} · {account.timezone}</span>
      </section>

      <section className="metric-grid analytics-metrics premium-metrics">
        <div className="metric-card card"><span>Expectancy</span><Pnl value={data.metrics.expectancy}><strong>{money(data.metrics.expectancy)}</strong></Pnl><small>Per normalized trade</small></div>
        <div className="metric-card card"><span>Profit factor</span><strong>{data.metrics.profit_factor ? Number(data.metrics.profit_factor).toFixed(2) : "Unavailable"}</strong><small>Gross wins divided by gross losses</small></div>
        <div className="metric-card card"><span>Average win / loss</span><strong>{data.metrics.average_win_loss_ratio ? Number(data.metrics.average_win_loss_ratio).toFixed(2) : "Unavailable"}</strong><small>Average payoff relationship</small></div>
        <div className="metric-card card"><span>Maximum drawdown</span><Pnl value={data.metrics.max_drawdown}><strong>{money(data.metrics.max_drawdown)}</strong></Pnl><small>Peak to trough canonical net</small></div>
      </section>

      <section className="pattern-scan">
        {scan.map((item) => (
          <article className={`pattern-callout card ${item.tone}`} key={item.label}>
            <span>{item.label}</span>
            <strong>{item.value}</strong>
            <p>{item.detail}</p>
          </article>
        ))}
      </section>

      <section className="analytics-detail-strip">
        <div><span>Total fees</span><strong>{money(data.metrics.total_fees)}</strong></div>
        <div><span>Fees / gross P&L</span><strong>{data.metrics.fees_percent_of_gross ? `${Number(data.metrics.fees_percent_of_gross).toFixed(1)}%` : "Unavailable"}</strong></div>
        <div><span>Average duration</span><strong>{data.metrics.average_duration_seconds ? `${Math.round(data.metrics.average_duration_seconds / 60)} min` : "Unavailable"}</strong></div>
        <div><span>Longest streaks</span><strong>{data.metrics.winning_streak} W · {data.metrics.losing_streak} L</strong></div>
      </section>

      <section className="analytics-grid premium-analytics-grid">
        <PerformanceBars title="By entry hour" eyebrow="Timing" rows={data.by_hour.map((row) => ({ ...row, label: hourLabel12(row.label) }))} />
        <PerformanceBars title="By weekday" eyebrow="Rhythm" rows={data.by_weekday} limit={7} />
        <PerformanceTable title="Long vs short" rows={data.by_side} />
        <PerformanceTable title="By root symbol" rows={data.by_root_symbol} />
        <PerformanceTable title="By grade" rows={data.by_grade} />
        <PerformanceTable title="Reviewed vs unreviewed" rows={data.by_review_status} />
      </section>
    </>
  );
}
