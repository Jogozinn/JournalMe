"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";

import { useAccount } from "@/components/account-provider";
import { ErrorState, PageHeader, Pnl, Skeleton } from "@/components/ui";
import { api, dateTime, money } from "@/lib/api";
import {
  applicable,
  cleanDecimalInput,
  optionalFormValue,
  scalingTiersFromForm,
  type ScalingTierInput,
} from "@/lib/prop";
import type { Account } from "@/lib/types";

type PropProfile = {
  id: string;
  firm_name: string;
  account_label: string | null;
  profile_account_type: string | null;
  starting_balance: string | null;
  profit_target: string | null;
  max_loss: string;
  daily_loss_limit: string | null;
  consistency_percent: string | null;
  drawdown_type: string | null;
  drawdown_amount: string | null;
  minimum_trading_days: number | null;
  payout_buffer: string | null;
  enabled: boolean;
  configuration_state: "configured" | "required";
  evaluation_drawdown_choice: string | null;
  daily_loss_limit_enabled: boolean | null;
  daily_loss_limit_amount: string | null;
  initial_trail_balance: string | null;
  locked_mll_balance: string | null;
  payout_buffer_balance_threshold: string | null;
  max_daily_simulated_profit: string | null;
  news_restriction_note: string | null;
  live_transition_note: string | null;
  purchase_configuration: Record<string, unknown>;
  qualifying_profit_days_required: number | null;
  minimum_profit_per_qualifying_day: string | null;
  payout_cycle_net_profit_required: boolean;
  minimum_payout: string | null;
  payout_profit_percentage: string | null;
  maximum_payout: string | null;
  maximum_payout_count: number | null;
  profit_split_trader_percent: string | null;
  profit_split_firm_percent: string | null;
  no_fixed_payout_window: boolean;
  payout_cycle_start_date: string | null;
  qualifying_days_since_last_payout: number;
  payouts_completed: number;
  preset_key: string | null;
  effective_date: string | null;
  source_note: string | null;
  scaling_tiers: ScalingTierInput[];
  version: { version_number: number; effective_date: string } | null;
};

type PropStatus = {
  verified: Record<string, string | number | null>;
  status: {
    current_balance: string | null;
    net_profit: string;
    profit_remaining: string | null;
    best_day_percent: string | null;
    additional_profit_for_consistency: string | null;
    maximum_loss_buffer: string | null;
    daily_loss_buffer: string | null;
    minimum_days_remaining: number | null;
    estimated_pass: boolean;
    maximum_loss_floor: string | null;
    high_water_balance: string | null;
  };
  configured: {
    profit_target: string | null;
    daily_loss_limit: string | null;
    consistency_percent: string | null;
    payout_buffer: string | null;
    minimum_profit_per_qualifying_day: string | null;
    payout_buffer_balance_threshold: string | null;
    max_daily_simulated_profit: string | null;
    news_restriction_note: string | null;
    live_transition_note: string | null;
  };
  payout_cycle: {
    start_date: string;
    cycle_net_profit: string;
    qualifying_day_count: number;
    qualifying_day_required: number | null;
    qualifying_day_dates: string[];
    eligible_for_payout: boolean;
    gross_available_payout: string | null;
    minimum_payout_met: boolean;
    requestable_payout: string | null;
    estimated_trader_share: string | null;
    estimated_firm_share: string | null;
    payouts_completed: number;
    maximum_payout_count: number | null;
    ineligibility_reasons: string[];
  };
  scaling: {
    current: ScalingTierInput | null;
    previous: ScalingTierInput | null;
    next: ScalingTierInput | null;
  };
  profile_version: {
    version_number: number;
    effective_date: string;
    source_note: string | null;
  } | null;
  formulas: Record<string, string>;
  warning: string;
};

type ManualAdjustment = {
  id: string;
  adjustment_type: string;
  amount: string;
  effective_at: string;
  reason: string;
  status: string;
};

type PayoutRecord = {
  id: string;
  request_date: string;
  approved_date: string | null;
  requested_amount: string;
  approved_gross_amount: string | null;
  trader_amount: string | null;
  firm_amount: string | null;
  status: string;
  notes: string | null;
};

export default function AccountDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { refresh } = useAccount();
  const [account, setAccount] = useState<Account | null>(null);
  const [profile, setProfile] = useState<PropProfile | null>(null);
  const [propStatus, setPropStatus] = useState<PropStatus | null>(null);
  const [adjustments, setAdjustments] = useState<ManualAdjustment[]>([]);
  const [payouts, setPayouts] = useState<PayoutRecord[]>([]);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [selectedPreset, setSelectedPreset] = useState("lucidflex-funded-50k");
  const [presetDrawdown, setPresetDrawdown] = useState("");
  const [presetDll, setPresetDll] = useState("");
  const load = useCallback(() => Promise.all([
    api<Account>(`/accounts/${id}`),
    api<PropProfile | null>(`/prop-rules/${id}`),
    api<PropStatus | null>(`/prop-rules/${id}/status`),
    api<ManualAdjustment[]>(`/manual-adjustments?account_id=${id}`),
    api<PayoutRecord[]>(`/prop-rules/${id}/payouts`),
  ]).then(([nextAccount, nextProfile, nextStatus, nextAdjustments, nextPayouts]) => {
    setAccount(nextAccount);
    setProfile(nextProfile);
    setPropStatus(nextStatus);
    setAdjustments(nextAdjustments);
    setPayouts(nextPayouts);
    if (nextAccount.configuration_required) {
      setSelectedPreset("lucid_daily_eval_50k");
    }
  }).catch((reason: Error) => setError(reason.message)), [id]);
  useEffect(() => {
    void load();
  }, [load]);
  async function saveAccount(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setSaving(true);
    try {
      await api(`/accounts/${id}`, { method: "PATCH", body: JSON.stringify({
        name: form.get("name"),
        account_type: form.get("account_type"),
        starting_balance: form.get("starting_balance") || null,
        timezone: form.get("timezone"),
        lifecycle_status: form.get("lifecycle_status"),
        notes: form.get("notes") || null,
      }) });
      await refresh();
      load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Account could not be saved.");
    } finally {
      setSaving(false);
    }
  }
  async function saveProp(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setSaving(true);
    setError("");
    try {
      await api(`/prop-rules/${id}`, { method: "PUT", body: JSON.stringify({
        firm_name: form.get("firm_name"),
        account_label: optionalFormValue(form, "account_label"),
        profile_account_type: optionalFormValue(form, "profile_account_type"),
        starting_balance: optionalFormValue(form, "prop_starting_balance"),
        profit_target: optionalFormValue(form, "profit_target"),
        max_loss: form.get("max_loss"),
        daily_loss_limit: optionalFormValue(form, "daily_loss_limit"),
        consistency_percent: optionalFormValue(form, "consistency_percent"),
        minimum_trading_days: optionalFormValue(form, "minimum_trading_days"),
        drawdown_type: optionalFormValue(form, "drawdown_type"),
        drawdown_amount: optionalFormValue(form, "drawdown_amount"),
        initial_trail_balance: optionalFormValue(form, "initial_trail_balance"),
        locked_mll_balance: optionalFormValue(form, "locked_mll_balance"),
        payout_buffer: optionalFormValue(form, "payout_buffer"),
        payout_buffer_balance_threshold: optionalFormValue(form, "payout_buffer_balance_threshold"),
        max_daily_simulated_profit: optionalFormValue(form, "max_daily_simulated_profit"),
        news_restriction_note: optionalFormValue(form, "news_restriction_note"),
        live_transition_note: optionalFormValue(form, "live_transition_note"),
        qualifying_profit_days_required: optionalFormValue(form, "qualifying_profit_days_required"),
        minimum_profit_per_qualifying_day: optionalFormValue(form, "minimum_profit_per_qualifying_day"),
        payout_cycle_net_profit_required: form.get("payout_cycle_net_profit_required") === "on",
        minimum_payout: optionalFormValue(form, "minimum_payout"),
        payout_profit_percentage: optionalFormValue(form, "payout_profit_percentage"),
        maximum_payout: optionalFormValue(form, "maximum_payout"),
        maximum_payout_count: optionalFormValue(form, "maximum_payout_count"),
        profit_split_trader_percent: optionalFormValue(form, "profit_split_trader_percent"),
        profit_split_firm_percent: optionalFormValue(form, "profit_split_firm_percent"),
        no_fixed_payout_window: form.get("no_fixed_payout_window") === "on",
        payout_cycle_start_date: optionalFormValue(form, "payout_cycle_start_date"),
        qualifying_days_since_last_payout: profile?.qualifying_days_since_last_payout ?? 0,
        payouts_completed: profile?.payouts_completed ?? 0,
        preset_key: profile?.preset_key ?? null,
        effective_date: optionalFormValue(form, "effective_date"),
        source_note: optionalFormValue(form, "source_note"),
        scaling_tiers: scalingTiersFromForm(form),
        rules_enabled_json: {
          profit_target: optionalFormValue(form, "profit_target") !== null,
          max_loss: true,
          daily_loss_limit: optionalFormValue(form, "daily_loss_limit") !== null,
          consistency: optionalFormValue(form, "consistency_percent") !== null,
          minimum_trading_days: optionalFormValue(form, "minimum_trading_days") !== null,
          qualifying_profit_days: optionalFormValue(form, "qualifying_profit_days_required") !== null,
          payout_cycle_net_profit: form.get("payout_cycle_net_profit_required") === "on",
        },
        enabled: true,
      }) });
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Prop rules could not be saved.");
    } finally {
      setSaving(false);
    }
  }
  async function updateArchiveState(action: "archive" | "restore") {
    setSaving(true);
    setError("");
    try {
      await api(`/accounts/${id}/${action}`, { method: "POST" });
      await refresh();
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : `Account could not be ${action}d.`);
    } finally {
      setSaving(false);
    }
  }
  async function applySelectedPreset(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    const replacing = Boolean(profile?.enabled && profile.preset_key !== selectedPreset);
    if (
      replacing &&
      !window.confirm("Replace the active profile with a new version copied from this preset?")
    ) return;
    setSaving(true);
    setError("");
    try {
      await api(`/prop-rules/${id}/apply-preset`, {
        method: "POST",
        body: JSON.stringify({
          preset_key: selectedPreset,
          confirm_replace: replacing,
          evaluation_drawdown_choice:
            selectedPreset === "lucid_daily_eval_50k" ? presetDrawdown || null : null,
          daily_loss_limit_enabled:
            selectedPreset.startsWith("lucid_daily")
              ? presetDll === "" ? null : presetDll === "on"
              : null,
        }),
      });
      await refresh();
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Preset could not be applied.");
    } finally {
      setSaving(false);
    }
  }
  async function createPayout(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setSaving(true);
    setError("");
    try {
      await api(`/prop-rules/${id}/payouts`, {
        method: "POST",
        body: JSON.stringify({
          request_date: form.get("request_date"),
          requested_amount: form.get("requested_amount"),
          notes: optionalFormValue(form, "payout_notes"),
        }),
      });
      event.currentTarget.reset();
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Payout could not be recorded.");
    } finally {
      setSaving(false);
    }
  }
  async function updatePayout(payoutId: string, status: "approved" | "rejected") {
    setSaving(true);
    setError("");
    try {
      await api(`/prop-rules/${id}/payouts/${payoutId}`, {
        method: "PATCH",
        body: JSON.stringify({
          status,
          approved_date: status === "approved" ? new Date().toISOString().slice(0, 10) : null,
          approved_gross_amount: null,
          reason: `Marked ${status} in JournalMe.`,
        }),
      });
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Payout could not be updated.");
    } finally {
      setSaving(false);
    }
  }
  async function addAdjustment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setSaving(true);
    try {
      await api("/manual-adjustments", {
        method: "POST",
        body: JSON.stringify({
          account_id: id,
          adjustment_type: form.get("adjustment_type"),
          amount: form.get("amount"),
          effective_at: new Date(String(form.get("effective_at"))).toISOString(),
          reason: form.get("reason"),
          status: form.get("adjustment_status"),
        }),
      });
      event.currentTarget.reset();
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Adjustment could not be recorded.");
    } finally {
      setSaving(false);
    }
  }
  async function approveAdjustment(adjustmentId: string) {
    setSaving(true);
    setError("");
    try {
      await api(`/manual-adjustments/${adjustmentId}`, {
        method: "PATCH",
        body: JSON.stringify({
          status: "approved",
          reason: "Approved in JournalMe.",
        }),
      });
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Adjustment could not be approved.");
    } finally {
      setSaving(false);
    }
  }
  if (!account) return error ? <ErrorState message={error} /> : <Skeleton rows={7} />;
  const tierRows = profile?.scaling_tiers.length
    ? profile.scaling_tiers
    : [{
        lower_profit_bound: "",
        upper_profit_bound: null,
        max_mini_contracts: 0,
        max_micro_contracts: 0,
      }];
  const today = new Date().toISOString().slice(0, 10);
  return (
    <>
      <PageHeader eyebrow={`${account.provider} · ${account.account_type}`} title={account.name} description={`All dates use ${account.timezone}. Imported and manual sources remain visibly distinct.`} action={<Link className="button" href="/accounts">All accounts</Link>} />
      {error && <ErrorState message={error} />}
      <section className="card account-balance-summary">
        <div><p className="eyebrow">Resolved account balance</p><h2>{money(account.current_balance, account.currency)}</h2><small>{account.balance_resolution.resolution_method.replaceAll("_", " ")} · starting balance {money(account.starting_balance, account.currency)}</small></div>
        <div className="plan-badges">{account.active_plan && <><span>{account.active_plan.plan_family}</span><span>{account.active_plan.phase}</span><span>50K</span></>}{account.configuration_required && <span className="warning-badge">Configuration required</span>}</div>
      </section>
      {account.configuration_required && <div className="notice warning"><strong>Configuration required.</strong> The historical LucidFlex version is preserved for audit, but it is inactive and does not determine this account’s badge or calculations. Choose the original LucidDaily evaluation drawdown and DLL purchase options below.</div>}
      <form className="card preset-apply-panel" onSubmit={applySelectedPreset}>
        <div className="section-title"><div><p className="eyebrow">Versioned preset catalog</p><h2>Apply an account preset</h2></div></div>
        <div className="form-grid">
          <div className="field"><label htmlFor="detail_preset">Preset</label><select id="detail_preset" value={selectedPreset} onChange={(event) => setSelectedPreset(event.target.value)}><option value="lucidflex-funded-50k">LucidFlex Funded 50K</option><option value="lucid_daily_eval_50k">LucidDaily Evaluation 50K</option><option value="lucid_daily_funded_50k">LucidDaily Funded 50K</option></select></div>
          {selectedPreset === "lucid_daily_eval_50k" && <div className="field"><label htmlFor="detail_drawdown">Evaluation drawdown</label><select id="detail_drawdown" value={presetDrawdown} onChange={(event) => setPresetDrawdown(event.target.value)} required><option value="">Choose…</option><option value="end_of_day_trailing">End-of-Day trailing</option><option value="intraday_trailing">Intraday trailing</option></select></div>}
          {selectedPreset.startsWith("lucid_daily") && <div className="field"><label htmlFor="detail_dll">Purchased DLL</label><select id="detail_dll" value={presetDll} onChange={(event) => setPresetDll(event.target.value)} required><option value="">Choose ON or OFF…</option><option value="on">ON · $1,200</option><option value="off">OFF · Not applicable</option></select></div>}
        </div>
        <p className="muted">Applying copies catalog values into a new immutable account-rule version. It never mutates the global preset or removes payout history.</p>
        <button className="button" disabled={saving}>Apply selected preset</button>
      </form>
      <section className="settings-layout">
        <form className="card settings-panel" onSubmit={saveAccount}>
          <p className="eyebrow">Account profile</p><h2>Identity and defaults</h2>
          <div className="form-grid">
            <div className="field"><label htmlFor="account_name">Name</label><input id="account_name" name="name" defaultValue={account.name} required /></div>
            <div className="field"><label htmlFor="account_type">Type</label><select id="account_type" name="account_type" defaultValue={account.account_type}><option value="simulated">Simulated</option><option value="evaluation">Evaluation</option><option value="funded">Funded</option><option value="personal">Personal</option></select></div>
            <div className="field"><label htmlFor="account_lifecycle_status">Lifecycle status</label><select id="account_lifecycle_status" name="lifecycle_status" defaultValue={account.lifecycle_status}><option value="active">Active</option><option value="passed">Passed</option><option value="funded">Funded</option><option value="blown">Blown</option><option value="closed">Closed</option></select></div>
            <div className="field"><label htmlFor="account_starting_balance">Starting balance</label><input id="account_starting_balance" name="starting_balance" defaultValue={account.starting_balance ?? ""} /></div>
            <div className="field"><label htmlFor="account_timezone">Timezone</label><input id="account_timezone" name="timezone" defaultValue={account.timezone} /></div>
            <div className="field span-2"><label htmlFor="account_notes">Notes</label><textarea id="account_notes" name="notes" defaultValue={account.notes ?? ""} /></div>
          </div>
          <button className="button primary" disabled={saving}>Save account</button>
          <div className="account-lifecycle-actions"><span>{account.active ? "This account appears in your active workspace." : "This account is archived and remains historically queryable."}</span><button className="button quiet" type="button" disabled={saving} onClick={() => void updateArchiveState(account.active ? "archive" : "restore")}>{account.active ? "Archive account" : "Restore account"}</button></div>
        </form>
        <form className="card settings-panel prop-profile-form" key={profile?.version?.version_number ?? "new"} onSubmit={saveProp}>
          <div className="section-title"><div><p className="eyebrow">Configurable rules</p><h2>Prop account profile</h2></div>{profile?.version && <span>Version {profile.version.version_number}</span>}</div>
          <p className="muted">These are your configured rules, not a contractual claim. Verify them against the current firm agreement.</p>
          <h3>Account and risk rules</h3>
          <div className="form-grid">
            <div className="field"><label htmlFor="firm_name">Firm name</label><input id="firm_name" name="firm_name" defaultValue={profile?.firm_name ?? ""} required /></div>
            <div className="field"><label htmlFor="account_label">Account label</label><input id="account_label" name="account_label" defaultValue={profile?.account_label ?? ""} /></div>
            <div className="field"><label htmlFor="profile_account_type">Account type</label><input id="profile_account_type" name="profile_account_type" defaultValue={profile?.profile_account_type ?? ""} /></div>
            <div className="field"><label htmlFor="prop_starting_balance">Rule starting balance</label><input id="prop_starting_balance" name="prop_starting_balance" inputMode="decimal" defaultValue={cleanDecimalInput(profile?.starting_balance ?? account.starting_balance)} /></div>
            <div className="field"><label htmlFor="profit_target">Profit target <small>optional</small></label><input id="profit_target" name="profit_target" inputMode="decimal" defaultValue={cleanDecimalInput(profile?.profit_target)} /></div>
            <div className="field"><label htmlFor="max_loss">Maximum loss</label><input id="max_loss" name="max_loss" inputMode="decimal" defaultValue={cleanDecimalInput(profile?.max_loss)} required /></div>
            <div className="field"><label htmlFor="daily_loss_limit">Daily loss limit <small>optional</small></label><input id="daily_loss_limit" name="daily_loss_limit" inputMode="decimal" defaultValue={cleanDecimalInput(profile?.daily_loss_limit)} /></div>
            <div className="field"><label htmlFor="consistency_percent">Consistency % <small>optional</small></label><input id="consistency_percent" name="consistency_percent" inputMode="decimal" defaultValue={cleanDecimalInput(profile?.consistency_percent)} /></div>
            <div className="field"><label htmlFor="minimum_trading_days">Minimum trading days</label><input id="minimum_trading_days" name="minimum_trading_days" type="number" min="1" defaultValue={profile?.minimum_trading_days ?? ""} /></div>
            <div className="field"><label htmlFor="drawdown_type">Drawdown type</label><select id="drawdown_type" name="drawdown_type" defaultValue={profile?.drawdown_type ?? "none"}><option value="none">None</option><option value="static">Static</option><option value="end_of_day_trailing">End-of-day trailing</option><option value="intraday_trailing">Intraday trailing</option></select></div>
            <div className="field"><label htmlFor="drawdown_amount">Drawdown amount</label><input id="drawdown_amount" name="drawdown_amount" inputMode="decimal" defaultValue={cleanDecimalInput(profile?.drawdown_amount)} /></div>
            <div className="field"><label htmlFor="initial_trail_balance">Initial trail balance</label><input id="initial_trail_balance" name="initial_trail_balance" inputMode="decimal" defaultValue={cleanDecimalInput(profile?.initial_trail_balance)} /></div>
            <div className="field"><label htmlFor="locked_mll_balance">Locked MLL balance</label><input id="locked_mll_balance" name="locked_mll_balance" inputMode="decimal" defaultValue={cleanDecimalInput(profile?.locked_mll_balance)} /></div>
            <div className="field"><label htmlFor="payout_buffer">Payout buffer <small>optional</small></label><input id="payout_buffer" name="payout_buffer" inputMode="decimal" defaultValue={cleanDecimalInput(profile?.payout_buffer)} /></div>
            <div className="field"><label htmlFor="payout_buffer_balance_threshold">Payout balance threshold</label><input id="payout_buffer_balance_threshold" name="payout_buffer_balance_threshold" inputMode="decimal" defaultValue={cleanDecimalInput(profile?.payout_buffer_balance_threshold)} /></div>
            <div className="field"><label htmlFor="max_daily_simulated_profit">Daily simulated-profit threshold</label><input id="max_daily_simulated_profit" name="max_daily_simulated_profit" inputMode="decimal" defaultValue={cleanDecimalInput(profile?.max_daily_simulated_profit)} /></div>
            <div className="field span-2"><label htmlFor="news_restriction_note">News restriction note</label><textarea id="news_restriction_note" name="news_restriction_note" defaultValue={profile?.news_restriction_note ?? ""} /></div>
            <div className="field span-2"><label htmlFor="live_transition_note">Live-transition note</label><textarea id="live_transition_note" name="live_transition_note" defaultValue={profile?.live_transition_note ?? ""} /></div>
          </div>
          <h3>Payout-cycle rules</h3>
          <div className="form-grid">
            <div className="field"><label htmlFor="qualifying_profit_days_required">Qualifying profit days required</label><input id="qualifying_profit_days_required" name="qualifying_profit_days_required" type="number" min="1" defaultValue={profile?.qualifying_profit_days_required ?? ""} /></div>
            <div className="field"><label htmlFor="minimum_profit_per_qualifying_day">Minimum profit per qualifying day</label><input id="minimum_profit_per_qualifying_day" name="minimum_profit_per_qualifying_day" inputMode="decimal" defaultValue={cleanDecimalInput(profile?.minimum_profit_per_qualifying_day)} /></div>
            <div className="field"><label htmlFor="minimum_payout">Minimum payout</label><input id="minimum_payout" name="minimum_payout" inputMode="decimal" defaultValue={cleanDecimalInput(profile?.minimum_payout)} /></div>
            <div className="field"><label htmlFor="payout_profit_percentage">Payout profit percentage</label><input id="payout_profit_percentage" name="payout_profit_percentage" inputMode="decimal" defaultValue={cleanDecimalInput(profile?.payout_profit_percentage)} /></div>
            <div className="field"><label htmlFor="maximum_payout">Maximum payout</label><input id="maximum_payout" name="maximum_payout" inputMode="decimal" defaultValue={cleanDecimalInput(profile?.maximum_payout)} /></div>
            <div className="field"><label htmlFor="maximum_payout_count">Maximum payout count</label><input id="maximum_payout_count" name="maximum_payout_count" type="number" min="1" defaultValue={profile?.maximum_payout_count ?? ""} /></div>
            <div className="field"><label htmlFor="profit_split_trader_percent">Trader profit split %</label><input id="profit_split_trader_percent" name="profit_split_trader_percent" inputMode="decimal" defaultValue={cleanDecimalInput(profile?.profit_split_trader_percent)} /></div>
            <div className="field"><label htmlFor="profit_split_firm_percent">Firm profit split %</label><input id="profit_split_firm_percent" name="profit_split_firm_percent" inputMode="decimal" defaultValue={cleanDecimalInput(profile?.profit_split_firm_percent)} /></div>
            <div className="field"><label htmlFor="payout_cycle_start_date">Payout cycle start date</label><input id="payout_cycle_start_date" name="payout_cycle_start_date" type="date" defaultValue={profile?.payout_cycle_start_date ?? ""} /></div>
            <label className="check-response"><input name="payout_cycle_net_profit_required" type="checkbox" defaultChecked={profile?.payout_cycle_net_profit_required ?? true} /> Require positive cycle net profit</label>
            <label className="check-response"><input name="no_fixed_payout_window" type="checkbox" defaultChecked={profile?.no_fixed_payout_window ?? false} /> No fixed payout window</label>
          </div>
          <h3>Scaling tiers</h3>
          <div className="scaling-tier-editor">
            {tierRows.map((tier, index) => <div className="form-grid" key={`${tier.lower_profit_bound}-${index}`}>
              <div className="field"><label>Lower profit bound</label><input aria-label={`Tier ${index + 1} lower profit bound`} name="tier_lower" inputMode="decimal" defaultValue={cleanDecimalInput(tier.lower_profit_bound)} /></div>
              <div className="field"><label>Upper profit bound</label><input aria-label={`Tier ${index + 1} upper profit bound`} name="tier_upper" inputMode="decimal" defaultValue={cleanDecimalInput(tier.upper_profit_bound)} /></div>
              <div className="field"><label>Maximum minis</label><input aria-label={`Tier ${index + 1} maximum minis`} name="tier_minis" type="number" min="0" defaultValue={tier.max_mini_contracts} /></div>
              <div className="field"><label>Maximum micros</label><input aria-label={`Tier ${index + 1} maximum micros`} name="tier_micros" type="number" min="0" defaultValue={tier.max_micro_contracts} /></div>
            </div>)}
          </div>
          <h3>Rule version</h3>
          <div className="form-grid">
            <div className="field"><label htmlFor="effective_date">Effective date</label><input id="effective_date" name="effective_date" type="date" defaultValue={profile?.effective_date ?? today} required /></div>
            <div className="field"><label htmlFor="source_note">Source note</label><input id="source_note" name="source_note" maxLength={1000} defaultValue={profile?.source_note ?? ""} /></div>
          </div>
          <button className="button primary" disabled={saving || account.configuration_required}>{account.configuration_required ? "Historical profile inactive" : profile ? "Update prop rules" : "Enable prop tracking"}</button>
        </form>
      </section>
      {propStatus && <section className="card prop-tracker">
        <div className="section-title"><div><p className="eyebrow">Payout cycle · rule version {propStatus.profile_version?.version_number ?? "Not available"}</p><h2>{propStatus.payout_cycle.eligible_for_payout ? "Eligible for a payout request" : "Payout requirements still in progress"}</h2></div><Pnl value={propStatus.payout_cycle.cycle_net_profit}>{money(propStatus.payout_cycle.cycle_net_profit)}</Pnl></div>
        <div className="prop-grid">
          <div><span>Resolved current balance</span><strong>{money(propStatus.status.current_balance)}</strong></div>
          <div><span>Cycle net profit</span><strong>{money(propStatus.payout_cycle.cycle_net_profit)}</strong></div>
          <div><span>Maximum-loss buffer</span><strong>{money(propStatus.status.maximum_loss_buffer)}</strong><small>{money(propStatus.status.current_balance)} − {money(propStatus.status.maximum_loss_floor)}</small></div>
          <div><span>Qualifying profit days</span><strong>{propStatus.payout_cycle.qualifying_day_count} / {propStatus.payout_cycle.qualifying_day_required ?? "Not applicable"}</strong><small>{propStatus.payout_cycle.qualifying_day_dates.join(" · ") || "No qualifying dates yet"}</small></div>
          <div><span>Minimum qualifying-day profit</span><strong>{applicable(propStatus.configured.minimum_profit_per_qualifying_day, money)}</strong></div>
          <div><span>Current scaling tier</span><strong>{propStatus.scaling.current ? `${propStatus.scaling.current.max_mini_contracts} minis / ${propStatus.scaling.current.max_micro_contracts} micros` : "Not configured"}</strong><small>{propStatus.scaling.current ? `${money(propStatus.scaling.current.lower_profit_bound)} to ${applicable(propStatus.scaling.current.upper_profit_bound, money)}` : "Add scaling tiers to the rule profile"}</small></div>
          <div><span>Previous scaling threshold</span><strong>{propStatus.scaling.previous ? money(propStatus.scaling.previous.lower_profit_bound) : "None"}</strong></div>
          <div><span>Next scaling threshold</span><strong>{propStatus.scaling.next ? money(propStatus.scaling.next.lower_profit_bound) : "Highest configured tier"}</strong></div>
          {propStatus.configured.payout_buffer_balance_threshold && <div><span>Payout balance threshold</span><strong>{money(propStatus.configured.payout_buffer_balance_threshold)}</strong><small>Gross maximum is profit above this balance</small></div>}
          {propStatus.configured.max_daily_simulated_profit && <div><span>Live-review daily threshold</span><strong>{money(propStatus.configured.max_daily_simulated_profit)}</strong><small>Firm review condition, not an automatic transition</small></div>}
        </div>
        <div className="prop-applicability">
          <div><span>Profit target</span><strong>{applicable(propStatus.configured.profit_target, money)}</strong></div>
          <div><span>Daily loss limit</span><strong>{applicable(propStatus.configured.daily_loss_limit, money)}</strong></div>
          <div><span>Consistency rule</span><strong>{applicable(propStatus.configured.consistency_percent, (value) => `${Number(value).toFixed(1)}%`)}</strong></div>
          <div><span>Payout buffer</span><strong>{applicable(propStatus.configured.payout_buffer, money)}</strong></div>
        </div>
        <div className="payout-summary">
          <article><span>Gross available payout</span><strong>{applicable(propStatus.payout_cycle.gross_available_payout, money)}</strong><small>Before eligibility and minimum-request checks</small></article>
          <article><span>Estimated trader share</span><strong>{applicable(propStatus.payout_cycle.estimated_trader_share, money)}</strong><small>Configured trader split</small></article>
          <article><span>Payouts completed</span><strong>{propStatus.payout_cycle.payouts_completed} / {propStatus.payout_cycle.maximum_payout_count ?? "Not applicable"}</strong></article>
        </div>
        {!propStatus.payout_cycle.eligible_for_payout && <div className="notice warning"><strong>Not eligible yet.</strong><ul>{propStatus.payout_cycle.ineligibility_reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul></div>}
        {propStatus.configured.news_restriction_note && <p className="notice warning"><strong>News restriction:</strong> {propStatus.configured.news_restriction_note}</p>}
        {propStatus.configured.live_transition_note && <p className="muted">{propStatus.configured.live_transition_note}</p>}
        <form className="payout-request form-grid" onSubmit={createPayout}>
          <div className="field"><label htmlFor="request_date">Request date</label><input id="request_date" name="request_date" type="date" defaultValue={today} required /></div>
          <div className="field"><label htmlFor="requested_amount">Requested gross amount</label><input id="requested_amount" name="requested_amount" inputMode="decimal" defaultValue={propStatus.payout_cycle.requestable_payout ?? ""} required /></div>
          <div className="field span-2"><label htmlFor="payout_notes">Notes</label><input id="payout_notes" name="payout_notes" maxLength={2000} /></div>
          <button className="button primary" disabled={saving || !propStatus.payout_cycle.eligible_for_payout}>Record payout request</button>
        </form>
        {!!payouts.length && <div className="payout-history"><h3>Payout records</h3>{payouts.map((item) => <article key={item.id}><div><strong>{money(item.requested_amount)}</strong><span className={`status-text ${item.status === "approved" ? "complete" : "partial"}`}>{item.status}</span></div><small>Requested {item.request_date}{item.approved_date ? ` · approved ${item.approved_date}` : ""}</small>{item.status === "pending" && <div className="form-actions"><button className="button" disabled={saving} onClick={() => void updatePayout(item.id, "rejected")}>Reject</button><button className="button primary" disabled={saving} onClick={() => void updatePayout(item.id, "approved")}>Approve</button></div>}</article>)}</div>}
        <details><summary>Calculation breakdown</summary>{Object.entries(propStatus.formulas).map(([name, formula]) => <p key={name}><strong>{name.replaceAll("_", " ")}:</strong> {formula}</p>)}</details>
        <p className="notice warning">{propStatus.warning}</p>
      </section>}
      <section className="card settings-panel manual-adjustments">
        <div className="section-title"><div><p className="eyebrow">Audited financial notes</p><h2>Manual adjustments</h2></div><span>{adjustments.length} recorded</span></div>
        <p className="muted">Deposits, withdrawals, and corrections stay separate from imported history and create an audit event.</p>
        {!!adjustments.length && <div className="group-list">{adjustments.map((item) => <div key={item.id}><strong>{item.adjustment_type.replaceAll("_", " ")} · {item.status}</strong><Pnl value={item.amount}>{money(item.amount)}</Pnl><small>{dateTime(item.effective_at)} · {item.reason}</small>{item.status === "pending" && <button className="button" disabled={saving} onClick={() => void approveAdjustment(item.id)}>Approve adjustment</button>}</div>)}</div>}
        <form className="form-grid" onSubmit={addAdjustment}>
          <div className="field"><label htmlFor="adjustment_type">Type</label><select id="adjustment_type" name="adjustment_type"><option value="deposit">Deposit</option><option value="withdrawal">Withdrawal</option><option value="fee_correction">Fee correction</option><option value="account_correction">Account correction</option></select></div>
          <div className="field"><label htmlFor="adjustment_amount">Amount</label><input id="adjustment_amount" name="amount" inputMode="decimal" required /></div>
          <div className="field"><label htmlFor="adjustment_effective_at">Effective time</label><input id="adjustment_effective_at" name="effective_at" type="datetime-local" required /></div>
          <div className="field"><label htmlFor="adjustment_reason">Reason</label><input id="adjustment_reason" name="reason" required maxLength={500} /></div>
          <div className="field"><label htmlFor="adjustment_status">Approval state</label><select id="adjustment_status" name="adjustment_status" defaultValue="approved"><option value="approved">Approved</option><option value="pending">Pending</option></select></div>
          <button className="button primary" disabled={saving}>Record adjustment</button>
        </form>
      </section>
    </>
  );
}
