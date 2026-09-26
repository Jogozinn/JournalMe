"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { useAccount } from "@/components/account-provider";
import { EmptyState, ErrorState, PageHeader, Pnl, Skeleton } from "@/components/ui";
import { api, money, percent } from "@/lib/api";
import type { Metrics } from "@/lib/types";

type CalendarPayload = {
  year: number;
  month: number;
  days: {
    date: string;
    net_pnl: string;
    trade_count: number;
    journaled: boolean;
  }[];
  summary: Metrics & {
    trading_days: number;
    journaled_days: number;
    best_day: string | null;
    worst_day: string | null;
  };
};

export default function CalendarPage() {
  const { account, loading } = useAccount();
  const now = useMemo(() => new Date(), []);
  const [month, setMonth] = useState(new Date(now.getFullYear(), now.getMonth(), 1));
  const [data, setData] = useState<CalendarPayload | null>(null);
  const [yearData, setYearData] = useState<CalendarPayload[]>([]);
  const [view, setView] = useState<"month" | "week" | "year">("month");
  const [error, setError] = useState("");
  useEffect(() => {
    if (!account) return;
    const requests = view === "year"
      ? Array.from({ length: 12 }, (_, index) => api<CalendarPayload>(`/calendar?account_id=${account.id}&year=${month.getFullYear()}&month=${index + 1}`))
      : [api<CalendarPayload>(`/calendar?account_id=${account.id}&year=${month.getFullYear()}&month=${month.getMonth() + 1}`)];
    Promise.all(requests)
      .then((payloads) => {
        setYearData(view === "year" ? payloads : []);
        setData(payloads[0] ?? null);
      })
      .catch((reason: Error) => setError(reason.message));
  }, [account, month, view]);

  const cells = useMemo(() => {
    const start = new Date(month.getFullYear(), month.getMonth(), 1).getDay();
    const count = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
    return [
      ...Array.from({ length: start }, () => null),
      ...Array.from({ length: count }, (_, index) => index + 1),
    ];
  }, [month]);
  const days = new Map(data?.days.map((day) => [Number(day.date.slice(-2)), day]) ?? []);
  const maxAbsPnl = Math.max(1, ...(data?.days.map((day) => Math.abs(Number(day.net_pnl))) ?? [1]));
  const rankedSessions = useMemo(
    () => [...(data?.days ?? [])].sort((a, b) => Number(b.net_pnl) - Number(a.net_pnl)),
    [data],
  );
  const bestSession = rankedSessions[0] ?? null;
  const hardestSession = rankedSessions.at(-1) ?? null;
  const journalCoverage = data?.summary.trading_days
    ? Math.round((data.summary.journaled_days / data.summary.trading_days) * 100)
    : 0;
  const weekRows = useMemo(() => {
    const currentMonth =
      month.getFullYear() === now.getFullYear() && month.getMonth() === now.getMonth();
    const anchor = currentMonth
      ? new Date(now.getFullYear(), now.getMonth(), now.getDate())
      : new Date(month.getFullYear(), month.getMonth(), 1);
    anchor.setDate(anchor.getDate() - ((anchor.getDay() + 6) % 7));
    const byDate = new Map(data?.days.map((day) => [day.date, day]) ?? []);
    return Array.from({ length: 7 }, (_, index) => {
      const date = new Date(anchor);
      date.setDate(anchor.getDate() + index);
      const dateKey = [
        date.getFullYear(),
        String(date.getMonth() + 1).padStart(2, "0"),
        String(date.getDate()).padStart(2, "0"),
      ].join("-");
      return { date, dateKey, record: byDate.get(dateKey) };
    });
  }, [data, month, now]);

  if (loading) return <Skeleton rows={5} />;
  if (!account) return <EmptyState title="Create an account first." copy="The calendar tells the story of one account." href="/" action="Set up account" />;
  return (
    <>
      <PageHeader
        eyebrow="Trading day archive"
        title="Calendar"
        description="See the month at a glance, then open any day to revisit what happened."
        action={
          <div className="calendar-actions">
            <div className="segmented">{(["month", "week", "year"] as const).map((item) => <button className={view === item ? "selected" : ""} key={item} onClick={() => setView(item)}>{item}</button>)}</div>
            <div className="month-controls">
            <button className="button" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))} aria-label="Previous month">‹</button>
            <strong>{month.toLocaleDateString([], { month: view === "year" ? undefined : "long", year: "numeric" })}</strong>
            <button className="button" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))} aria-label="Next month">›</button>
            </div>
          </div>
        }
      />
      {error && <ErrorState message={error} />}
      {!data ? (
        <Skeleton rows={5} />
      ) : (
        <>
          <section className="calendar-metrics">
            <div><span>Monthly net</span><Pnl value={data.summary.net_pnl}>{money(data.summary.net_pnl)}</Pnl></div>
            <div><span>Win rate</span><strong>{percent(data.summary.win_rate)}</strong></div>
            <div><span>Trading days</span><strong>{data.summary.trading_days}</strong></div>
            <div><span>Journaled</span><strong>{data.summary.journaled_days}</strong></div>
          </section>
          {view !== "year" && (
            <section className="calendar-highlights" aria-label="Month highlights">
              <div className="calendar-highlight positive">
                <span>Best session</span>
                <strong>{bestSession ? new Date(`${bestSession.date}T12:00:00`).toLocaleDateString([], { weekday: "long", month: "short", day: "numeric" }) : "No session yet"}</strong>
                <Pnl value={bestSession?.net_pnl ?? null}>{bestSession ? money(bestSession.net_pnl) : "No P&L"}</Pnl>
              </div>
              <div className="calendar-highlight negative">
                <span>Hardest session</span>
                <strong>{hardestSession ? new Date(`${hardestSession.date}T12:00:00`).toLocaleDateString([], { weekday: "long", month: "short", day: "numeric" }) : "No session yet"}</strong>
                <Pnl value={hardestSession?.net_pnl ?? null}>{hardestSession ? money(hardestSession.net_pnl) : "No P&L"}</Pnl>
              </div>
              <div className="calendar-highlight">
                <span>Review coverage</span>
                <strong>{journalCoverage}%</strong>
                <small>{data.summary.journaled_days} of {data.summary.trading_days} trading days journaled</small>
              </div>
            </section>
          )}
          {view === "year" ? <section className="year-grid">
            {yearData.map((item) => <button className="card year-month" key={item.month} onClick={() => { setMonth(new Date(item.year, item.month - 1, 1)); setView("month"); }}><span>{new Date(item.year, item.month - 1, 1).toLocaleDateString([], { month: "long" })}</span><Pnl value={item.summary.net_pnl}>{money(item.summary.net_pnl)}</Pnl><small>{item.summary.trading_days} trading day{item.summary.trading_days === 1 ? "" : "s"} · {item.summary.journaled_days} journaled</small></button>)}
          </section> : view === "week" ? <section className="week-calendar">
            {weekRows.map(({ date, dateKey, record }) => <Link className="card week-day-row" href={`/timeline/${dateKey}`} key={dateKey}><div><strong>{date.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" })}</strong><span>{record ? `${record.trade_count} trade${record.trade_count === 1 ? "" : "s"}` : "No trades"}</span></div><span className={`status-text ${record?.journaled ? "complete" : record ? "partial" : ""}`}>{record ? (record.journaled ? "Journaled" : "Needs recap") : "Quiet"}</span>{record ? <Pnl value={record.net_pnl}>{money(record.net_pnl)}</Pnl> : <span className="muted">Quiet</span>}</Link>)}
          </section> : <section className="calendar-grid card">
            {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((label) => <span className="weekday" key={label}>{label}</span>)}
            {cells.map((day, index) => {
              if (!day) return <span className="calendar-cell blank" key={`blank-${index}`} />;
              const record = days.get(day);
              const dateKey = `${month.getFullYear()}-${String(month.getMonth() + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
              return record ? (() => {
                const pnl = Number(record.net_pnl);
                const intensity = Math.min(1, Math.abs(pnl) / maxAbsPnl);
                return (
                  <Link className={`calendar-cell active-day ${pnl > 0 ? "gain-day" : pnl < 0 ? "loss-day" : "flat-day"} ${intensity >= 0.67 ? "heat-high" : intensity >= 0.34 ? "heat-medium" : "heat-low"}`} href={`/timeline/${dateKey}`} key={dateKey}>
                    <span className="calendar-day-number">{day}</span>
                    <div className="calendar-result">
                      <Pnl value={record.net_pnl}>{money(record.net_pnl)}</Pnl>
                      <small>{record.trade_count} trade{record.trade_count === 1 ? "" : "s"}</small>
                    </div>
                    <div className="calendar-cell-footer">
                      <span>{record.journaled ? "Journal complete" : "Needs recap"}</span>
                      <i className="calendar-meter" aria-hidden="true"><b style={{ width: `${Math.max(12, intensity * 100)}%` }} /></i>
                    </div>
                  </Link>
                );
              })() : (
                <Link className="calendar-cell" href={`/timeline/${dateKey}`} key={dateKey}>
                  <span>{day}</span>
                </Link>
              );
            })}
          </section>}
        </>
      )}
    </>
  );
}
