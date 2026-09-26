"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { useAccount } from "@/components/account-provider";
import { EmptyState, ErrorState, PageHeader, Pnl, Skeleton } from "@/components/ui";
import { api, money } from "@/lib/api";
import type { ReviewStatus } from "@/lib/types";

type TradingDay = {
  date: string;
  net_pnl: string;
  trade_count: number;
  day_grade: string | null;
  review: ReviewStatus;
};

export default function TradingDaysPage() {
  const { account, loading } = useAccount();
  const [days, setDays] = useState<TradingDay[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!account) return;
    api<{ items: TradingDay[] }>(`/trading-days?account_id=${account.id}`)
      .then((payload) => {
        setDays(payload.items);
        setError("");
      })
      .catch((reason: Error) => setError(reason.message));
  }, [account]);

  const maxAbsPnl = useMemo(
    () => Math.max(1, ...days.map((day) => Math.abs(Number(day.net_pnl)))),
    [days],
  );

  if (loading) return <Skeleton rows={6} />;
  if (!account) {
    return <EmptyState title="Create an account first." copy="Trading days belong to an account." href="/" action="Set up account" />;
  }

  return (
    <>
      <PageHeader
        eyebrow={`${account.name} · ${account.timezone}`}
        title="Trading Days"
        description="Every session in one place, with the result and the reflection beside it."
        action={<Link className="button primary" href={`/timeline/${new Date().toISOString().slice(0, 10)}`}>Plan today</Link>}
      />
      {error && <ErrorState message={error} />}
      {!days.length && !error ? (
        <EmptyState title="No trading days yet." copy="Plan today without creating a fake trade, or import your execution history." href={`/timeline/${new Date().toISOString().slice(0, 10)}`} action="Plan today" />
      ) : (
        <section className="day-list session-ledger">
          {days.map((day) => {
            const pnl = Number(day.net_pnl);
            const intensity = Math.max(8, Math.round((Math.abs(pnl) / maxAbsPnl) * 100));
            return (
              <Link className="card day-list-item session-row" href={`/timeline/${day.date}`} key={day.date}>
                <div className="session-date">
                  <small>{new Date(`${day.date}T12:00:00`).toLocaleDateString([], { weekday: "long" })}</small>
                  <strong>{new Date(`${day.date}T12:00:00`).toLocaleDateString([], { month: "long", day: "numeric", year: "numeric" })}</strong>
                </div>
                <div className="session-pulse" aria-hidden="true">
                  <i className={pnl > 0 ? "gain" : pnl < 0 ? "loss" : "flat"} style={{ width: `${intensity}%` }} />
                </div>
                <div className="session-stat"><span>Trades</span><strong>{day.trade_count}</strong></div>
                <div className="session-stat"><span>Grade</span><strong>{day.day_grade ?? "Not graded"}</strong></div>
                <div className="session-stat"><span>Review</span><strong className={`status-text ${day.review.status}`}>{day.review.status}</strong></div>
                <div className="session-result"><Pnl value={day.net_pnl}>{money(day.net_pnl)}</Pnl><span>Open session</span></div>
              </Link>
            );
          })}
        </section>
      )}
    </>
  );
}
