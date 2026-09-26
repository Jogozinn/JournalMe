"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";

import { ErrorState, PageHeader, Pnl, Skeleton } from "@/components/ui";
import { api, dateTime, money } from "@/lib/api";
import type { ChecklistItem, Playbook, Trade } from "@/lib/types";

type Detail = Playbook & {
  analytics: {
    net_pnl: string;
    trade_count: number;
    win_rate: string | null;
    expectancy: string | null;
    adherence_percent: number | null;
  };
  linked_trades: Trade[];
  sample_size_warning: string | null;
};

export default function PlaybookDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [item, setItem] = useState<Detail | null>(null);
  const [checklist, setChecklist] = useState<ChecklistItem[]>([]);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const load = useCallback(() => api<Detail>(`/playbooks/${id}`)
    .then((payload) => {
      setItem(payload);
      setChecklist(payload.checklist_items);
    })
    .catch((reason: Error) => setError(reason.message)), [id]);
  useEffect(() => {
    void load();
  }, [load]);
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const text = (name: string) => String(form.get(name) || "") || null;
    setSaving(true);
    setSaved(false);
    try {
      await api(`/playbooks/${id}`, {
        method: "PUT",
        body: JSON.stringify({
          name: text("name"),
          description: text("description"),
          active: form.get("active") === "on",
          market_scope: text("market_scope"),
          direction_scope: text("direction_scope"),
          preferred_session: text("preferred_session"),
          minimum_confluences: form.get("minimum_confluences") ? Number(form.get("minimum_confluences")) : null,
          ideal_entry_criteria: text("ideal_entry_criteria"),
          confirmation_criteria: text("confirmation_criteria"),
          invalidation_criteria: text("invalidation_criteria"),
          stop_logic: text("stop_logic"),
          target_logic: text("target_logic"),
          management_rules: text("management_rules"),
          prohibited_conditions: text("prohibited_conditions"),
          default_grade_expectations: text("default_grade_expectations"),
          checklist_items: checklist.map((row, index) => ({
            ...(row.id ? { id: row.id } : {}),
            text: row.text,
            category: row.category,
            required: row.required,
            sort_order: index,
          })),
        }),
      });
      setSaved(true);
      load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Playbook could not be saved.");
    } finally {
      setSaving(false);
    }
  }
  if (!item) return error ? <ErrorState message={error} /> : <Skeleton rows={8} />;
  return (
    <>
      <PageHeader
        eyebrow="Playbook"
        title={item.name}
        description="Define the plan clearly enough that adherence can be reviewed without hindsight."
        action={<Link className="button" href="/playbooks">All playbooks</Link>}
      />
      {error && <ErrorState message={error} />}
      <section className="metric-grid analytics-metrics">
        <div className="metric-card card"><span>Sample size</span><strong>{item.analytics.trade_count}</strong><small>{item.sample_size_warning ?? "Descriptive results"}</small></div>
        <div className="metric-card card"><span>Net P&L</span><Pnl value={item.analytics.net_pnl}><strong>{money(item.analytics.net_pnl)}</strong></Pnl><small>Assigned trades</small></div>
        <div className="metric-card card"><span>Expectancy</span><strong>{money(item.analytics.expectancy)}</strong><small>Per assigned trade</small></div>
        <div className="metric-card card"><span>Adherence</span><strong>{item.analytics.adherence_percent === null ? "Unavailable" : `${item.analytics.adherence_percent}%`}</strong><small>Core checks passed</small></div>
      </section>
      <form className="playbook-editor" onSubmit={save}>
        <section className="card editor-section">
          <div className="section-title"><div><p className="eyebrow">Identity</p><h2>Scope and context</h2></div><label className="switch-row"><input name="active" type="checkbox" defaultChecked={item.active} /> Active</label></div>
          <div className="form-grid">
            <div className="field span-2"><label>Name</label><input name="name" defaultValue={item.name} required /></div>
            <div className="field span-2"><label>Description</label><textarea name="description" defaultValue={item.description ?? ""} /></div>
            <div className="field"><label>Market / instrument scope</label><input name="market_scope" defaultValue={item.market_scope ?? ""} /></div>
            <div className="field"><label>Direction scope</label><select name="direction_scope" defaultValue={item.direction_scope ?? "both"}><option value="both">Both</option><option value="long">Long</option><option value="short">Short</option></select></div>
            <div className="field"><label>Preferred session</label><input name="preferred_session" defaultValue={item.preferred_session ?? ""} /></div>
            <div className="field"><label>Minimum confluences</label><input name="minimum_confluences" type="number" min="0" defaultValue={item.minimum_confluences ?? ""} /></div>
          </div>
        </section>
        <section className="card editor-section">
          <p className="eyebrow">Written plan</p><h2>Decision rules</h2>
          <div className="form-grid">
            {[["ideal_entry_criteria", "Ideal entry criteria"], ["confirmation_criteria", "Confirmation criteria"], ["invalidation_criteria", "Invalidation criteria"], ["stop_logic", "Stop logic"], ["target_logic", "Target logic"], ["management_rules", "Management rules"], ["prohibited_conditions", "Prohibited conditions"], ["default_grade_expectations", "Grade expectations"]].map(([name, label]) => <div className="field" key={name}><label>{label}</label><textarea name={name} defaultValue={String(item[name as keyof Detail] ?? "")} /></div>)}
          </div>
        </section>
        <section className="card editor-section">
          <div className="section-title"><div><p className="eyebrow">Adherence</p><h2>Checklist</h2></div><button type="button" className="button" onClick={() => setChecklist([...checklist, { id: "", playbook_id: item.id, text: "", category: "entry", required: true, sort_order: checklist.length }])}>Add item</button></div>
          <div className="checklist-editor">
            {checklist.map((row, index) => <div key={row.id || `new-${index}`}><input aria-label="Checklist text" value={row.text} onChange={(event) => setChecklist(checklist.map((itemRow, rowIndex) => rowIndex === index ? { ...itemRow, text: event.target.value } : itemRow))} required /><select value={row.category} onChange={(event) => setChecklist(checklist.map((itemRow, rowIndex) => rowIndex === index ? { ...itemRow, category: event.target.value } : itemRow))}><option value="entry">Entry</option><option value="confirmation">Confirmation</option><option value="risk">Risk</option><option value="management">Management</option></select><label className={`checklist-priority ${row.required ? "core" : "optional"}`}><input type="checkbox" checked={row.required} onChange={(event) => setChecklist(checklist.map((itemRow, rowIndex) => rowIndex === index ? { ...itemRow, required: event.target.checked } : itemRow))} /><span>{row.required ? "Must pass" : "Optional"}</span></label><button type="button" className="button danger" onClick={() => setChecklist(checklist.filter((_, rowIndex) => rowIndex !== index))}>Remove</button></div>)}
          </div>
        </section>
        <div className="sticky-save"><span>{saved ? "All changes saved" : "Review your plan before saving"}</span><button className="button primary" disabled={saving}>{saving ? "Saving..." : "Save playbook"}</button></div>
      </form>
      <section className="card linked-trades">
        <div className="section-title"><h2>Linked trades</h2><span>{item.linked_trades.length} shown</span></div>
        {item.linked_trades.length ? item.linked_trades.map((trade) => <Link href={`/trades/${trade.id}`} key={trade.id}><div><strong>{trade.symbol}</strong><span>{dateTime(trade.entry_timestamp)}</span></div><Pnl value={trade.net_pnl}>{money(trade.net_pnl)}</Pnl></Link>) : <p className="muted">Assign this playbook during Trade Review to build a sample.</p>}
      </section>
    </>
  );
}
