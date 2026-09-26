"use client";

import Link from "next/link";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";

import { useAccount } from "@/components/account-provider";
import { Icon } from "@/components/icons";
import { EmptyState, ErrorState, PageHeader, Pnl, Skeleton } from "@/components/ui";
import { api, dateTime, money, percent, quantity } from "@/lib/api";
import type { Metrics, Trade } from "@/lib/types";

const EquityChart = dynamic(() => import("@/components/equity-chart"), {
  ssr: false,
  loading: () => <div className="chart-loading" aria-label="Loading equity chart" />,
});

type Dashboard = {
  balance: string | null;
  balance_as_of: string | null;
  balance_resolution: {
    resolution_method: string;
    stale_snapshot: boolean;
    imported_balance: string | null;
    calculated_balance: string | null;
    reconciliation_difference: string | null;
  };
  metrics: Metrics;
  equity_curve: { at: string; value: string }[];
  recent_trades: Trade[];
  journal_completion: {
    completed: number;
    trading_days: number;
    percent: number;
  };
  latest_insight: string | null;
  period: { value: string; start: string | null; end: string | null; timezone: string };
};

type ReviewSummary = {
  trades_awaiting_review: number;
  days_awaiting_recap: number;
  review_streak: number;
  completion_percent: number;
};

type DaySummary = {
  date: string;
  net_pnl: string;
  trade_count: number;
  review: { status: string };
};

type Goal = {
  id: string;
  custom_goal_text: string | null;
  goal_type: string;
  current_value: string | null;
  effective_target: string | null;
  progress_percent: number;
  on_track: boolean | null;
};

const metricLabels: [keyof Metrics, string, "money" | "percent" | "number"][] = [
  ["net_pnl", "Net P&L", "money"],
  ["win_rate", "Win rate", "percent"],
  ["profit_factor", "Profit factor", "number"],
  ["average_winner", "Average winner", "money"],
  ["average_loser", "Average loser", "money"],
  ["expectancy", "Expectancy", "money"],
];

function AccountSetup() {
  const { refresh } = useAccount();
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setSaving(true);
    setError("");
    try {
      await api("/accounts", {
        method: "POST",
        body: JSON.stringify({
          name: form.get("name"),
          account_type: form.get("account_type"),
          starting_balance: form.get("starting_balance") || null,
          timezone: "America/New_York",
          currency: "USD",
        }),
      });
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Account setup failed.");
    } finally {
      setSaving(false);
    }
  }
  return (
    <section className="account-setup card">
      <p className="eyebrow">Begin your journal</p>
      <h2>Create your first trading account</h2>
      <p>
        Name the account you review. JournalMe can detect and remember its broker
        identifier during your first import.
      </p>
      {error && <ErrorState message={error} />}
      <form onSubmit={submit} className="form-grid">
        <div className="field">
          <label htmlFor="account-name">Account name</label>
          <input id="account-name" name="name" defaultValue="My trading account" required />
        </div>
        <div className="field">
          <label htmlFor="account-type">Account type</label>
          <select id="account-type" name="account_type" defaultValue="simulated">
            <option value="simulated">Simulated</option>
            <option value="evaluation">Evaluation</option>
            <option value="funded">Funded</option>
            <option value="personal">Personal</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="starting-balance">Starting balance (optional)</label>
          <input id="starting-balance" name="starting_balance" inputMode="decimal" />
        </div>
        <button className="button primary setup-submit" disabled={saving}>
          {saving ? "Creating…" : "Create account"}
        </button>
      </form>
    </section>
  );
}

export default function HomePage() {
  const router = useRouter();
  const { account, loading: accountLoading } = useAccount();
  const [data, setData] = useState<Dashboard | null>(null);
  const [review, setReview] = useState<ReviewSummary | null>(null);
  const [days, setDays] = useState<DaySummary[]>([]);
  const [goals, setGoals] = useState<Goal[]>([]);
  const [prop, setProp] = useState<Record<string, unknown> | null>(null);
  const [period, setPeriod] = useState("all");
  const [customStart, setCustomStart] = useState(
    `${new Date().getFullYear()}-${String(new Date().getMonth() + 1).padStart(2, "0")}-01`,
  );
  const [customEnd, setCustomEnd] = useState(new Date().toISOString().slice(0, 10));
  const [error, setError] = useState("");
  useEffect(() => {
    if (!account) {
      setData(null);
      return;
    }
    setError("");
    const dashboardRequest = api<Dashboard>(
      `/dashboard?account_id=${account.id}&period=${period}` +
        (period === "custom" ? `&start=${customStart}&end=${customEnd}` : ""),
    );
    void Promise.allSettled([
      dashboardRequest,
      api<ReviewSummary>(`/review-summary?account_id=${account.id}`),
      api<{ items: DaySummary[] }>(`/trading-days?account_id=${account.id}&page_size=60`),
      api<Goal[]>(`/goals?account_id=${account.id}`),
      api<Record<string, unknown> | null>(`/prop-rules/${account.id}/status`),
    ]).then(([dashboard, queue, tradingDays, nextGoals, propStatus]) => {
      if (dashboard.status === "rejected") {
        setError(dashboard.reason instanceof Error ? dashboard.reason.message : "Dashboard could not be loaded.");
        return;
      }
      setData(dashboard.value);
      setReview(queue.status === "fulfilled" ? queue.value : null);
      setDays(tradingDays.status === "fulfilled" ? tradingDays.value.items : []);
      setGoals(nextGoals.status === "fulfilled" ? nextGoals.value : []);
      setProp(propStatus.status === "fulfilled" ? propStatus.value : null);
    });
  }, [account, period, customEnd, customStart]);
  useEffect(() => {
    if (!account || !data) return;
    data.recent_trades.forEach((trade) => router.prefetch(`/trades/${trade.id}`));
    router.prefetch("/review");
    router.prefetch("/calendar");
  }, [account, data, router]);

  if (accountLoading) return <Skeleton rows={5} />;
  if (!account) {
    return (
      <>
        <PageHeader
          eyebrow="Welcome to JournalMe"
          title="Your trading story starts here."
          description="Set up one account, then bring in your reports as a single, calm import."
        />
        <AccountSetup />
      </>
    );
  }
  if (error) return <ErrorState message={error} />;
  if (!data) return <Skeleton rows={5} />;
  const hasTrades = data.metrics.total_trades > 0;
  const today = new Intl.DateTimeFormat("en-CA", {
    timeZone: account.timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
  const todayRecord = days.find((day) => day.date === today);
  const activeGoal = goals.find((goal) => goal.goal_type === "pnl_target") ?? goals[0];
  const propStatus = (prop?.status ?? null) as {
    net_profit?: string;
    profit_remaining?: string;
    estimated_pass?: boolean;
  } | null;
  const propPayout = (prop?.payout_cycle ?? null) as {
    cycle_net_profit?: string;
    qualifying_day_count?: number;
    qualifying_day_required?: number | null;
    eligible_for_payout?: boolean;
  } | null;
  return (
    <>
      <PageHeader
        eyebrow={new Intl.DateTimeFormat("en-US", {
          weekday: "long",
          month: "long",
          day: "numeric",
        }).format(new Date())}
        title="Welcome back."
        description={`A clear view of ${account.name}, one trading day at a time.`}
        action={<div className="dashboard-periods">
          <div className="period-control" aria-label="Dashboard period">
            {[
              ["today", "Today"],
              ["week", "This week"],
              ["month", "This month"],
              ["all", "All time"],
              ["custom", "Custom"],
            ].map(([value, label]) => <button key={value} className={period === value ? "selected" : ""} onClick={() => setPeriod(value)}>{label}</button>)}
          </div>
          {period === "custom" && <div className="custom-range">
            <label htmlFor="dashboard-start">From</label>
            <input id="dashboard-start" type="date" value={customStart} max={customEnd} onChange={(event) => setCustomStart(event.target.value)} />
            <label htmlFor="dashboard-end">To</label>
            <input id="dashboard-end" type="date" value={customEnd} min={customStart} onChange={(event) => setCustomEnd(event.target.value)} />
          </div>}
        </div>}
      />
      {!hasTrades ? (
        <EmptyState
          title="Your journal is ready for its first session."
          copy="Quick Sync your Tradovate Performance and Fills reports. JournalMe will recognize, reconcile, and build your day automatically."
          href="/settings/connections"
          action="Sync Tradovate"
        />
      ) : (
        <>
          <section className="today-workflow card">
            <div>
              <p className="eyebrow">Today · {account.timezone}</p>
              <h2>{!todayRecord ? "Plan the session before the first trade." : todayRecord.review.status === "complete" ? "Today’s journal is complete." : "Today is ready to review."}</h2>
              <p>{!todayRecord ? "Record your mindset, limits, allowed playbooks, and written plan." : `${todayRecord.trade_count} trade${todayRecord.trade_count === 1 ? "" : "s"} · ${money(todayRecord.net_pnl)} net · ${todayRecord.review.status} review`}</p>
            </div>
            <div className="quick-actions">
              <Link className="button primary" href={`/timeline/${today}`}>{todayRecord ? "Review today" : "Plan today"}</Link>
              <Link className="button" href="/review">Review queue</Link>
              <Link className="button" href="/manual-trade">Add manual trade</Link>
              <Link className="button quiet" href="/settings/connections"><Icon name="import" /> Sync Tradovate</Link>
            </div>
          </section>
          <section className="metric-grid">
            <article className="metric-card card hero-metric">
              <span>Current balance</span>
              <strong className="metric-value">{money(data.balance)}</strong>
              <small>
                {data.balance_resolution.resolution_method === "imported_snapshot"
                  ? `Imported balance · ${data.balance_as_of}`
                  : data.balance_resolution.resolution_method === "stale_snapshot_roll_forward"
                    ? `Snapshot rolled forward · ${data.balance_as_of}`
                    : "Calculated from the canonical ledger"}
              </small>
            </article>
            {metricLabels.slice(0, 3).map(([key, label, format]) => {
              const value = data.metrics[key];
              const display =
                format === "money"
                  ? money(value)
                  : format === "percent"
                    ? percent(value)
                    : value === null
                      ? "Unavailable"
                      : Number(value).toFixed(2);
              return (
                <article className="metric-card card" key={key}>
                  <span>{label}</span>
                  <Pnl value={key === "net_pnl" ? String(value) : null}>
                    <strong className="metric-value">{display}</strong>
                  </Pnl>
                  <small>{key === "net_pnl" ? "After imported fill fees" : "All imported trades"}</small>
                </article>
              );
            })}
          </section>
          <section className="week-strip card" aria-label="Current week">
            {Array.from({ length: 7 }, (_, index) => {
              const date = new Date(`${today}T12:00:00`);
              const mondayOffset = (date.getDay() + 6) % 7;
              date.setDate(date.getDate() - mondayOffset + index);
              const key = date.toISOString().slice(0, 10);
              const record = days.find((day) => day.date === key);
              return <Link href={`/timeline/${key}`} className={key === today ? "today" : ""} key={key}><span>{date.toLocaleDateString([], { weekday: "short" })}</span><strong>{date.getDate()}</strong>{record ? <Pnl value={record.net_pnl}>{money(record.net_pnl)}</Pnl> : <small>Quiet</small>}</Link>;
            })}
          </section>
          <section className="home-grid">
            <article className="card chart-card">
              <div className="section-title">
                <div>
                  <p className="eyebrow">Equity story</p>
                  <h2>Cumulative net P&L</h2>
                </div>
                <Pnl value={data.metrics.net_pnl}>
                  {money(data.metrics.net_pnl)}
                </Pnl>
              </div>
              <div className="chart-wrap">
                <EquityChart points={data.equity_curve} />
              </div>
            </article>
            <article className="card journal-progress">
              <p className="eyebrow">Daily practice</p>
              <h2>Journal completion</h2>
              <div
                className="progress-ring"
                style={{
                  background: `conic-gradient(var(--accent) ${data.journal_completion.percent}%, var(--surface-raised) 0)`,
                }}
              >
                <span>{data.journal_completion.percent}%</span>
              </div>
              <p>
                {data.journal_completion.completed} of{" "}
                {data.journal_completion.trading_days} trading days reflected.
              </p>
              <Link href="/review">Open review queue <Icon name="arrow" /></Link>
            </article>
          </section>
          <section className="home-lower">
            <article className="card recent-card">
              <div className="section-title">
                <h2>Recent trades</h2>
                <Link href="/trades">View all</Link>
              </div>
              <div className="recent-list">
                {data.recent_trades.map((trade) => (
                  <Link href={`/trades/${trade.id}`} key={trade.id}>
                    <div>
                      <strong>{trade.symbol}</strong>
                      <span>{trade.side} · {quantity(trade.quantity, true)} · {dateTime(trade.entry_timestamp, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</span>
                    </div>
                    <Pnl value={trade.net_pnl}>{money(trade.net_pnl)}</Pnl>
                  </Link>
                ))}
              </div>
            </article>
            <div className="home-stack">
              <article className="card insight-card">
                <p className="eyebrow">Review practice</p>
                <h2>{review?.trades_awaiting_review ?? 0} trades awaiting review</h2>
                <p>{review?.days_awaiting_recap ?? 0} day recaps remain · {review?.completion_percent ?? 0}% complete · {review?.review_streak ?? 0} day streak.</p>
              </article>
              {activeGoal && <article className="card insight-card">
                <p className="eyebrow">Current goal</p>
                <h2>{activeGoal.custom_goal_text ?? activeGoal.goal_type.replaceAll("_", " ")}</h2>
                <div className="linear-progress"><i style={{ width: `${activeGoal.progress_percent}%` }} /></div>
                <p>{activeGoal.current_value ?? "Unavailable"} of {activeGoal.effective_target ?? "Unavailable"} · {activeGoal.on_track === null ? "Tracking" : activeGoal.on_track ? "On track" : "Needs attention"}</p>
              </article>}
              {propStatus && <article className="card insight-card">
                <p className="eyebrow">Prop account · configured rules</p>
                <h2>{money(propPayout?.cycle_net_profit ?? propStatus.net_profit)} cycle profit</h2>
                <p>{propPayout ? `${propPayout.qualifying_day_count ?? 0} / ${propPayout.qualifying_day_required ?? "Not available"} qualifying profit days · ${propPayout.eligible_for_payout ? "Payout eligible" : "In progress"}` : `${money(propStatus.profit_remaining)} remaining · ${propStatus.estimated_pass ? "Estimated rules met" : "In progress"}`}. Verify against your firm agreement.</p>
              </article>}
              <article className="card insight-card">
                <p className="eyebrow">Stored-data reminder</p>
                <h2>Latest reminder</h2>
                <p>{data.latest_insight ?? "Keep journaling. A useful pattern needs a little more history."}</p>
              </article>
            </div>
          </section>
        </>
      )}
    </>
  );
}
