"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { useAccount } from "@/components/account-provider";
import { EmptyState, ErrorState, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import type { Playbook, Tag } from "@/lib/types";

export default function ManualTradePage() {
  const { account } = useAccount();
  const router = useRouter();
  const [playbooks, setPlaybooks] = useState<Playbook[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [gross, setGross] = useState("");
  const [fees, setFees] = useState("0");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    Promise.all([api<Playbook[]>("/playbooks?active=true"), api<Tag[]>("/tags")])
      .then(([nextPlaybooks, nextTags]) => {
        setPlaybooks(nextPlaybooks);
        setTags(nextTags);
      })
      .catch((reason: Error) => setError(reason.message));
  }, []);
  if (!account) return <EmptyState title="Create an account first." copy="Manual records must be assigned explicitly." href="/" action="Set up account" />;
  const net = gross === "" ? "" : (Number(gross) - Number(fees || 0)).toFixed(2);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!account) return;
    const form = new FormData(event.currentTarget);
    setSaving(true);
    setError("");
    try {
      const created = await api<{ id: string }>("/manual-trades", {
        method: "POST",
        body: JSON.stringify({
          account_id: account.id,
          symbol: form.get("symbol"),
          root_symbol: form.get("root_symbol") || null,
          side: form.get("side"),
          quantity: form.get("quantity"),
          entry_timestamp: new Date(String(form.get("entry_timestamp"))).toISOString(),
          exit_timestamp: new Date(String(form.get("exit_timestamp"))).toISOString(),
          entry_price: form.get("entry_price"),
          exit_price: form.get("exit_price"),
          gross_pnl: gross,
          fees,
          net_pnl: net,
          notes: form.get("notes") || null,
          primary_playbook_id: form.get("primary_playbook_id") || null,
          tag_ids: form.getAll("tag_ids"),
        }),
      });
      router.push(`/trades/${created.id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Manual trade could not be created.");
      setSaving(false);
    }
  }
  return (
    <>
      <PageHeader
        eyebrow={`Manual financial record · ${account.name}`}
        title="Add manual trade"
        description="Use this only when broker data is unavailable. The source remains visibly manual and creation is audited."
      />
      {error && <ErrorState message={error} />}
      <form className="card manual-form" onSubmit={submit}>
        <div className="notice warning"><strong>Manual source</strong><p>This record will not be merged invisibly with imported history. Net P&L must equal gross P&L minus fees.</p></div>
        <div className="form-grid">
          <div className="field"><label htmlFor="manual_symbol">Symbol</label><input id="manual_symbol" name="symbol" required maxLength={80} placeholder="MESU6" /></div>
          <div className="field"><label htmlFor="manual_root_symbol">Root symbol</label><input id="manual_root_symbol" name="root_symbol" maxLength={40} placeholder="MES" /></div>
          <div className="field"><label htmlFor="manual_side">Side</label><select id="manual_side" name="side"><option value="long">Long</option><option value="short">Short</option></select></div>
          <div className="field"><label htmlFor="manual_quantity">Quantity</label><input id="manual_quantity" name="quantity" inputMode="decimal" required /></div>
          <div className="field"><label htmlFor="entry_timestamp">Entry time ({account.timezone})</label><input id="entry_timestamp" name="entry_timestamp" type="datetime-local" required /></div>
          <div className="field"><label htmlFor="exit_timestamp">Exit time ({account.timezone})</label><input id="exit_timestamp" name="exit_timestamp" type="datetime-local" required /></div>
          <div className="field"><label htmlFor="manual_entry_price">Entry price</label><input id="manual_entry_price" name="entry_price" inputMode="decimal" required /></div>
          <div className="field"><label htmlFor="manual_exit_price">Exit price</label><input id="manual_exit_price" name="exit_price" inputMode="decimal" required /></div>
          <div className="field"><label htmlFor="manual_gross_pnl">Gross P&amp;L</label><input id="manual_gross_pnl" value={gross} onChange={(event) => setGross(event.target.value)} inputMode="decimal" required /></div>
          <div className="field"><label htmlFor="manual_fees">Fees</label><input id="manual_fees" value={fees} onChange={(event) => setFees(event.target.value)} inputMode="decimal" required /></div>
          <div className="field"><label htmlFor="manual_net_pnl">Net P&amp;L</label><input id="manual_net_pnl" value={net} readOnly aria-readonly /></div>
          <div className="field"><label htmlFor="manual_playbook">Primary playbook</label><select id="manual_playbook" name="primary_playbook_id"><option value="">Not assigned</option>{playbooks.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></div>
          <div className="field span-2"><label htmlFor="manual_notes">Notes</label><textarea id="manual_notes" name="notes" /></div>
        </div>
        <fieldset className="manual-tags"><legend>Tags</legend>{tags.map((tag) => <label key={tag.id}><input type="checkbox" name="tag_ids" value={tag.id} /> {tag.name}</label>)}</fieldset>
        <div className="form-actions"><button className="button primary" disabled={saving}>{saving ? "Creating audited record…" : "Create manual trade"}</button></div>
      </form>
    </>
  );
}
