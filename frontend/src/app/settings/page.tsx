"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

import { useAccount } from "@/components/account-provider";
import { ErrorState, PageHeader, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";

type Preferences = {
  timezone: string;
  currency: string;
  week_start: number;
  default_account_id: string | null;
  default_date_range: string;
  pnl_display: string;
  density: string;
  reduced_motion: boolean;
  review_rules_json: Record<string, unknown>;
};

export default function SettingsPage() {
  const { accounts } = useAccount();
  const [preferences, setPreferences] = useState<Preferences | null>(null);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    api<Preferences>("/preferences")
      .then(setPreferences)
      .catch((reason: Error) => setError(reason.message));
  }, []);
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      const next = await api<Preferences>("/preferences", {
        method: "PUT",
        body: JSON.stringify({
          timezone: form.get("timezone"),
          currency: form.get("currency"),
          week_start: Number(form.get("week_start")),
          default_account_id: form.get("default_account_id") || null,
          default_date_range: form.get("default_date_range"),
          pnl_display: form.get("pnl_display"),
          density: form.get("density"),
          reduced_motion: form.get("reduced_motion") === "on",
        }),
      });
      setPreferences(next);
      setSaved(true);
      window.setTimeout(() => setSaved(false), 2000);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Preferences could not be saved.");
    }
  }
  return (
    <>
      <PageHeader eyebrow="Personal workspace" title="Settings" description="Defaults should reduce friction without hiding where financial data came from." />
      {error && <ErrorState message={error} />}
      <section className="settings-link-grid">
        <Link className="card more-card" href="/settings/connections"><div><h2>Broker connections</h2><p>Manage live desktop bridges, catch-up connectors, and sync health.</p></div></Link>
        <Link className="card more-card" href="/intelligence"><div><h2>Trader intelligence</h2><p>Choose the accounts that contribute to cross-account learning.</p></div></Link>
        <Link className="card more-card" href="/captures"><div><h2>Chrome Companion</h2><p>Review chart captures saved from the browser sidebar. Use Connect web inside the extension to link this account.</p></div></Link>
        <Link className="card more-card" href="/accounts"><div><h2>Accounts & prop rules</h2><p>Identity, account types, timezone, notes, groups, and configurable limits.</p></div></Link>
        <Link className="card more-card" href="/playbooks"><div><h2>Playbooks</h2><p>Trading plans, ordered checklists, examples, and archive state.</p></div></Link>
        <Link className="card more-card" href="/goals"><div><h2>Goals</h2><p>Calm metric-linked goals for daily, weekly, monthly, or custom periods.</p></div></Link>
        <Link className="card more-card" href="/imports"><div><h2>Imports & data quality</h2><p>Session history, source coverage, reconciliation, and retained canceled orders.</p></div></Link>
        <Link className="card more-card" href="/settings/data"><div><h2>Data & backups</h2><p>Portable CSV, JSON, and complete ZIP exports with local backup status.</p></div></Link>
        <Link className="card more-card" href="/review"><div><h2>Review completion</h2><p>See the explicit requirements and work through incomplete reviews.</p></div></Link>
      </section>
      {!preferences ? <Skeleton rows={5} /> : <form className="card settings-panel preference-panel" onSubmit={save}>
        <div className="section-title"><div><p className="eyebrow">Trading preferences</p><h2>Display and workflow defaults</h2></div><span className={saved ? "positive" : "muted"}>{saved ? "Saved" : "Local profile"}</span></div>
        <div className="form-grid">
          <div className="field"><label>Timezone</label><input name="timezone" defaultValue={preferences.timezone} /></div>
          <div className="field"><label>Currency</label><input name="currency" defaultValue={preferences.currency} maxLength={3} /></div>
          <div className="field"><label>Week starts</label><select name="week_start" defaultValue={preferences.week_start}><option value="1">Monday</option><option value="0">Sunday</option></select></div>
          <div className="field"><label>Default account</label><select name="default_account_id" defaultValue={preferences.default_account_id ?? ""}><option value="">Most recent</option>{accounts.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></div>
          <div className="field"><label>Default date range</label><select name="default_date_range" defaultValue={preferences.default_date_range}><option value="today">Today</option><option value="this_week">This week</option><option value="this_month">This month</option><option value="all">All time</option></select></div>
          <div className="field"><label>P&L emphasis</label><select name="pnl_display" defaultValue={preferences.pnl_display}><option value="net">Net P&L</option><option value="gross">Gross P&L</option></select></div>
          <div className="field"><label>Density</label><select name="density" defaultValue={preferences.density}><option value="comfortable">Comfortable</option><option value="compact">Compact</option></select></div>
          <label className="switch-row"><input name="reduced_motion" type="checkbox" defaultChecked={preferences.reduced_motion} /> Reduce motion</label>
        </div>
        <div className="notice"><strong>Default completion rules</strong><p>Trade: thesis, entry reason, exit reason, lesson, grade, followed-plan answer, primary playbook, a tag, and required checklist answers. Day: reflection, next-session focus, grade, followed-rules answer, and complete trade reviews.</p></div>
        <button className="button primary">Save preferences</button>
      </form>}
    </>
  );
}
