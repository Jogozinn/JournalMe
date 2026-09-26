"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

import { useAccount } from "@/components/account-provider";
import { EmptyState, ErrorState, PageHeader, Pnl, Skeleton } from "@/components/ui";
import { api, money, percent } from "@/lib/api";

type Payload = {
  start_date: string;
  end_date: string;
  metrics: {
    net_pnl: string;
    fees: string | null;
    trade_count: number;
    win_rate: string | null;
    profit_factor: string | null;
    expectancy: string | null;
    best_day: { date: string; net_pnl: string } | null;
    worst_day: { date: string; net_pnl: string } | null;
    most_used_playbook: { name: string; trades: number } | null;
    journal_completion_percent: number;
  };
  review: Record<string, string | null> | null;
};

export function PeriodReview({
  kind,
  periodStart,
}: {
  kind: "weekly" | "monthly";
  periodStart: string;
}) {
  const { account, loading } = useAccount();
  const [data, setData] = useState<Payload | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const load = () => {
    if (!account) return;
    api<Payload>(`/reviews/${kind}/${periodStart}?account_id=${account.id}`)
      .then(setData)
      .catch((reason: Error) => setError(reason.message));
  };
  useEffect(load, [account, kind, periodStart]);
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!account) return;
    const form = new FormData(event.currentTarget);
    const value = (name: string) => String(form.get(name) || "") || null;
    setSaving(true);
    setSaved(false);
    try {
      const next = await api<Payload>(`/reviews/${kind}/${periodStart}?account_id=${account.id}`, {
        method: "PUT",
        body: JSON.stringify({
          written_review: value("written_review"),
          what_worked: value("what_worked"),
          what_failed: value("what_failed"),
          next_period_focus: value("next_period_focus"),
          next_period_goals: value("next_period_goals"),
          grade: value("grade"),
        }),
      });
      setData(next);
      setSaved(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Review could not be saved.");
    } finally {
      setSaving(false);
    }
  }
  if (loading) return <Skeleton rows={7} />;
  if (!account) return <EmptyState title="Create an account first." copy="Period reviews belong to one account." href="/" action="Set up account" />;
  if (!data) return error ? <ErrorState message={error} /> : <Skeleton rows={7} />;
  const review = data.review ?? {};
  return (
    <>
      <PageHeader
        eyebrow={`${kind === "weekly" ? "Weekly" : "Monthly"} review · ${account.name}`}
        title={`${new Date(`${data.start_date}T12:00:00`).toLocaleDateString([], { month: "long", day: "numeric" })} to ${new Date(`${data.end_date}T12:00:00`).toLocaleDateString([], { month: "long", day: "numeric", year: "numeric" })}`}
        description="Financial summaries are calculated from the canonical ledger; your conclusions stay editable."
        action={<Link className="button" href="/review">Review queue</Link>}
      />
      {error && <ErrorState message={error} />}
      <section className="metric-grid analytics-metrics">
        <div className="metric-card card"><span>Net P&L</span><Pnl value={data.metrics.net_pnl}><strong>{money(data.metrics.net_pnl)}</strong></Pnl><small>After fees</small></div>
        <div className="metric-card card"><span>Win rate</span><strong>{percent(data.metrics.win_rate)}</strong><small>{data.metrics.trade_count} trades</small></div>
        <div className="metric-card card"><span>Profit factor</span><strong>{data.metrics.profit_factor ? Number(data.metrics.profit_factor).toFixed(2) : "Unavailable"}</strong><small>{money(data.metrics.fees)} fees</small></div>
        <div className="metric-card card"><span>Journal completion</span><strong>{data.metrics.journal_completion_percent}%</strong><small>Explicit review rules</small></div>
      </section>
      <section className="period-insights">
        <article className="card"><span>Best day</span><Pnl value={data.metrics.best_day?.net_pnl ?? null}>{data.metrics.best_day ? money(data.metrics.best_day.net_pnl) : "Unavailable"}</Pnl><small>{data.metrics.best_day?.date ?? "No trading days"}</small></article>
        <article className="card"><span>Worst day</span><Pnl value={data.metrics.worst_day?.net_pnl ?? null}>{data.metrics.worst_day ? money(data.metrics.worst_day.net_pnl) : "Unavailable"}</Pnl><small>{data.metrics.worst_day?.date ?? "No trading days"}</small></article>
        <article className="card"><span>Most used playbook</span><strong>{data.metrics.most_used_playbook?.name ?? "Unavailable"}</strong><small>{data.metrics.most_used_playbook ? `${data.metrics.most_used_playbook.trades} trades` : "Assign playbooks in Trade Review"}</small></article>
      </section>
      <form className="card period-review-form" onSubmit={save}>
        <div className="section-title"><div><p className="eyebrow">Written review</p><h2>Turn the period into a useful next step</h2></div><span className={saved ? "saved" : ""}>{saved ? "Saved" : "Stored with this period"}</span></div>
        <div className="field"><label htmlFor="written_review">Overall review</label><textarea id="written_review" name="written_review" defaultValue={review.written_review ?? ""} /></div>
        <div className="form-grid">
          <div className="field"><label htmlFor="period_what_worked">What worked</label><textarea id="period_what_worked" name="what_worked" defaultValue={review.what_worked ?? ""} /></div>
          <div className="field"><label htmlFor="what_failed">What failed</label><textarea id="what_failed" name="what_failed" defaultValue={review.what_failed ?? ""} /></div>
          <div className="field"><label htmlFor="next_period_focus">Next {kind === "weekly" ? "week" : "month"} focus</label><textarea id="next_period_focus" name="next_period_focus" defaultValue={review.next_period_focus ?? ""} /></div>
          <div className="field"><label htmlFor="next_period_goals">Next {kind === "weekly" ? "week" : "month"} goals</label><textarea id="next_period_goals" name="next_period_goals" defaultValue={review.next_period_goals ?? ""} /></div>
          <div className="field"><label htmlFor="period_grade">Grade</label><select id="period_grade" name="grade" defaultValue={review.grade ?? ""}><option value="">Not graded</option>{["A+", "A", "B", "C", "D", "F"].map((grade) => <option key={grade}>{grade}</option>)}</select></div>
        </div>
        <div className="form-actions"><button className="button primary" disabled={saving}>{saving ? "Saving..." : `Save ${kind} review`}</button></div>
      </form>
    </>
  );
}
