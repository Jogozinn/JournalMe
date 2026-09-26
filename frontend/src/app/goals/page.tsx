"use client";

import { FormEvent, useEffect, useState } from "react";

import { useAccount } from "@/components/account-provider";
import { EmptyState, ErrorState, PageHeader, Pnl, Skeleton } from "@/components/ui";
import { api, money } from "@/lib/api";

type Goal = {
  id: string;
  goal_type: string;
  period_type: string;
  start_date: string;
  end_date: string;
  custom_goal_text: string | null;
  current_value: string | null;
  effective_target: string | null;
  progress_percent: number;
  on_track: boolean | null;
  status: string;
};

export default function GoalsPage() {
  const { account, loading } = useAccount();
  const [goals, setGoals] = useState<Goal[]>([]);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");
  const load = () => {
    if (!account) return;
    api<Goal[]>(`/goals?account_id=${account.id}`)
      .then(setGoals)
      .catch((reason: Error) => setError(reason.message));
  };
  useEffect(load, [account]);
  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!account) return;
    const form = new FormData(event.currentTarget);
    const type = String(form.get("goal_type"));
    const target = form.get("target_value") || null;
    try {
      await api("/goals", { method: "POST", body: JSON.stringify({
        account_id: account.id,
        goal_type: type,
        period_type: form.get("period_type"),
        start_date: form.get("start_date"),
        end_date: form.get("end_date"),
        target_value: target,
        target_pnl: type === "pnl_target" ? target : null,
        target_journal_days: type === "journal_completion" && target ? Number(target) : null,
        custom_goal_text: form.get("custom_goal_text") || null,
      }) });
      setCreating(false);
      load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Goal could not be created.");
    }
  }
  async function archive(id: string) {
    await api(`/goals/${id}`, { method: "PATCH", body: JSON.stringify({ status: "archived" }) });
    load();
  }
  if (loading) return <Skeleton rows={5} />;
  if (!account) return <EmptyState title="Create an account first." copy="Goals track one account without blending its ledger." href="/" action="Set up account" />;
  const today = new Date().toISOString().slice(0, 10);
  const monthEnd = `${today.slice(0, 8)}${new Date(Number(today.slice(0, 4)), Number(today.slice(5, 7)), 0).getDate()}`;
  return (
    <>
      <PageHeader eyebrow="Progress without pressure" title="Goals" description="Use a clear metric or a written intention. JournalMe reports progress without guilt-oriented copy." action={<button className="button primary" onClick={() => setCreating((value) => !value)}>{creating ? "Cancel" : "Create goal"}</button>} />
      {error && <ErrorState message={error} />}
      {creating && <form className="card create-panel" onSubmit={create}>
        <div className="form-grid">
          <div className="field"><label htmlFor="goal_type">Goal type</label><select id="goal_type" name="goal_type"><option value="pnl_target">P&L target</option><option value="max_daily_loss">Maximum daily loss</option><option value="max_weekly_loss">Maximum weekly loss</option><option value="journal_completion">Journal completion</option><option value="a_grade_trades">A-grade trades</option><option value="plan_adherence">Plan adherence %</option><option value="max_trades_per_day">Maximum trades per day</option><option value="mistake_reduction">Mistake reduction</option><option value="custom">Custom</option></select></div>
          <div className="field"><label htmlFor="period_type">Period</label><select id="period_type" name="period_type"><option value="daily">Daily</option><option value="weekly">Weekly</option><option value="monthly">Monthly</option><option value="custom">Custom</option></select></div>
          <div className="field"><label htmlFor="goal_start_date">Start</label><input id="goal_start_date" name="start_date" type="date" defaultValue={today} required /></div>
          <div className="field"><label htmlFor="goal_end_date">End</label><input id="goal_end_date" name="end_date" type="date" defaultValue={monthEnd} required /></div>
          <div className="field"><label htmlFor="target_value">Target value</label><input id="target_value" name="target_value" inputMode="decimal" /></div>
          <div className="field span-2"><label htmlFor="custom_goal_text">Personal wording</label><input id="custom_goal_text" name="custom_goal_text" placeholder="What would useful progress look like?" /></div>
        </div>
        <button className="button primary">Create goal</button>
      </form>}
      {!goals.length ? <EmptyState title="No active goals." copy="Create a measured goal or a quiet written intention for the next period." href="#" action="Create goal" /> : <section className="goal-grid">
        {goals.map((goal) => <article className={`card goal-card ${goal.status}`} key={goal.id}>
          <div><span className="eyebrow">{goal.period_type} · {goal.goal_type.replaceAll("_", " ")}</span><span>{goal.status}</span></div>
          <h2>{goal.custom_goal_text ?? goal.goal_type.replaceAll("_", " ")}</h2>
          <div className="linear-progress"><i style={{ width: `${goal.progress_percent}%` }} /></div>
          <div className="goal-values"><Pnl value={goal.goal_type === "pnl_target" ? goal.current_value : null}>{goal.goal_type === "pnl_target" ? money(goal.current_value) : goal.current_value ?? "Unavailable"}</Pnl><span>of {goal.goal_type === "pnl_target" ? money(goal.effective_target) : goal.effective_target ?? "Unavailable"}</span></div>
          <footer><span>{goal.start_date} to {goal.end_date}</span>{goal.status === "active" && <button className="button quiet" onClick={() => void archive(goal.id)}>Archive</button>}</footer>
        </article>)}
      </section>}
    </>
  );
}
