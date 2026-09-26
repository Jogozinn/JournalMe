"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

import { ErrorState } from "@/components/ui";
import { api, money } from "@/lib/api";

type Preset = {
  preset_key: string;
  provider: string;
  plan_family: string;
  account_phase: string;
  account_size: string | null;
  display_name: string;
  required_fields: string[];
  rules: Record<string, unknown>;
};

const CUSTOM_PLAN = "Custom";
const DEFAULT_TIMEZONE = "America/New_York";

function unique(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))];
}

function prettyPlan(value: string): string {
  return value.replace(/([a-z])([A-Z])/g, "$1 $2");
}

function prettyPhase(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function defaultName(plan: string, phase: string, size: string | null): string {
  if (plan === CUSTOM_PLAN) return "My trading account";
  const sizeLabel = size ? `${Math.round(Number(size) / 1000)}K` : "";
  return [prettyPlan(plan), prettyPhase(phase), sizeLabel, "#1"].filter(Boolean).join(" ");
}

export function PresetWizard({
  onSaved,
  onCancel,
}: {
  onSaved: () => Promise<void>;
  onCancel: () => void;
}) {
  const [presets, setPresets] = useState<Preset[]>([]);
  const [loadingPresets, setLoadingPresets] = useState(true);
  const [step, setStep] = useState(1);
  const [plan, setPlan] = useState("");
  const [phase, setPhase] = useState("");
  const [accountSize, setAccountSize] = useState("");
  const [drawdown, setDrawdown] = useState("");
  const [dll, setDll] = useState("");
  const [name, setName] = useState("");
  const [nameTouched, setNameTouched] = useState(false);
  const [externalId, setExternalId] = useState("");
  const [customType, setCustomType] = useState("evaluation");
  const [customBalance, setCustomBalance] = useState("50000");
  const [customTimezone, setCustomTimezone] = useState(DEFAULT_TIMEZONE);
  const [customFirmName, setCustomFirmName] = useState("Custom");
  const [customProfitTarget, setCustomProfitTarget] = useState("");
  const [customMaxLoss, setCustomMaxLoss] = useState("");
  const [customDailyLoss, setCustomDailyLoss] = useState("");
  const [customConsistency, setCustomConsistency] = useState("");
  const [customMinimumDays, setCustomMinimumDays] = useState("");
  const [customDrawdownType, setCustomDrawdownType] = useState("");
  const [customDrawdownAmount, setCustomDrawdownAmount] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let alive = true;
    api<Preset[]>("/prop-presets")
      .then((items) => {
        if (!alive) return;
        setPresets(items);
      })
      .catch((reason: Error) => {
        if (alive) setError(reason.message);
      })
      .finally(() => {
        if (alive) setLoadingPresets(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  const planOptions = useMemo(() => {
    const catalog = unique(presets.map((item) => item.plan_family));
    return unique([...catalog, CUSTOM_PLAN]);
  }, [presets]);

  useEffect(() => {
    if (plan || planOptions.length === 0) return;
    const preferred = planOptions.includes("LucidFlex") ? "LucidFlex" : planOptions[0];
    setPlan(preferred);
  }, [plan, planOptions]);

  const planPresets = useMemo(
    () => presets.filter((item) => item.plan_family === plan),
    [plan, presets],
  );
  const phaseOptions = useMemo(
    () => unique(planPresets.map((item) => item.account_phase)),
    [planPresets],
  );

  useEffect(() => {
    if (plan === CUSTOM_PLAN) {
      setPhase(customType);
      return;
    }
    if (!phaseOptions.length) {
      setPhase("");
      return;
    }
    if (!phaseOptions.includes(phase)) setPhase(phaseOptions[0]);
  }, [customType, phase, phaseOptions, plan]);

  const phasePresets = useMemo(
    () => planPresets.filter((item) => item.account_phase === phase),
    [phase, planPresets],
  );
  const sizeOptions = useMemo(
    () => unique(phasePresets.map((item) => item.account_size ?? "")),
    [phasePresets],
  );

  useEffect(() => {
    if (plan === CUSTOM_PLAN) {
      setAccountSize(customBalance);
      return;
    }
    if (!sizeOptions.length) {
      setAccountSize("");
      return;
    }
    if (!sizeOptions.includes(accountSize)) setAccountSize(sizeOptions[0]);
  }, [accountSize, customBalance, plan, sizeOptions]);

  const preset = useMemo(
    () => phasePresets.find((item) => (item.account_size ?? "") === accountSize) ?? phasePresets[0],
    [accountSize, phasePresets],
  );

  useEffect(() => {
    if (nameTouched) return;
    setName(defaultName(plan, phase, plan === CUSTOM_PLAN ? customBalance : preset?.account_size ?? accountSize));
  }, [accountSize, customBalance, nameTouched, phase, plan, preset?.account_size]);

  const requiresDrawdown = Boolean(
    preset?.required_fields?.includes("evaluation_drawdown_choice") ||
      (plan === "LucidDaily" && phase.toLowerCase() === "evaluation"),
  );
  const requiresDll = Boolean(
    preset?.required_fields?.includes("daily_loss_limit_enabled") || plan === "LucidDaily",
  );
  const customRulesRequested = [
    customProfitTarget,
    customMaxLoss,
    customDailyLoss,
    customConsistency,
    customMinimumDays,
    customDrawdownType,
    customDrawdownAmount,
  ].some((value) => value.trim() !== "");
  const customRulesComplete = !customRulesRequested || customMaxLoss.trim() !== "";
  const configurationComplete =
    plan === CUSTOM_PLAN
      ? customRulesComplete
      : Boolean(preset) &&
        (!requiresDrawdown || drawdown !== "") &&
        (!requiresDll || dll !== "");

  useEffect(() => {
    setDrawdown("");
    setDll("");
  }, [preset?.preset_key]);

  function choosePlan(nextPlan: string) {
    setPlan(nextPlan);
    setStep(1);
    setNameTouched(false);
    setError("");
  }

  function next() {
    setError("");
    if (step === 1 && !plan) {
      setError("Choose a plan or Custom account first.");
      return;
    }
    if (step === 2 && plan !== CUSTOM_PLAN && !phase) {
      setError("Choose an account phase.");
      return;
    }
    if (step === 3 && plan !== CUSTOM_PLAN && !preset) {
      setError("No preset exists for that plan, phase, and account size yet.");
      return;
    }
    if (step === 4 && !configurationComplete) {
      setError("Complete the required configuration before continuing.");
      return;
    }
    setStep((value) => Math.min(value + 1, 5));
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!configurationComplete) return;
    if (plan !== CUSTOM_PLAN && !preset) {
      setError("This preset combination is not available yet.");
      return;
    }

    setSaving(true);
    setError("");
    try {
      if (plan === CUSTOM_PLAN) {
        const created = await api<{ id: string }>("/accounts", {
          method: "POST",
          body: JSON.stringify({
            name,
            account_type: customType,
            starting_balance: customBalance || null,
            timezone: customTimezone || DEFAULT_TIMEZONE,
            currency: "USD",
          }),
        });
        if (customRulesRequested) {
          await api(`/prop-rules/${created.id}`, {
            method: "PUT",
            body: JSON.stringify({
              firm_name: customFirmName.trim() || "Custom",
              account_label: name,
              profile_account_type: customType,
              starting_balance: customBalance || null,
              profit_target: customProfitTarget || null,
              max_loss: customMaxLoss,
              daily_loss_limit: customDailyLoss || null,
              consistency_percent: customConsistency || null,
              minimum_trading_days: customMinimumDays || null,
              drawdown_type: customDrawdownType || null,
              drawdown_amount: customDrawdownAmount || null,
              initial_trail_balance: null,
              locked_mll_balance: null,
              payout_buffer: null,
              payout_buffer_balance_threshold: null,
              max_daily_simulated_profit: null,
              news_restriction_note: null,
              live_transition_note: null,
              qualifying_profit_days_required: null,
              minimum_profit_per_qualifying_day: null,
              payout_cycle_net_profit_required: false,
              minimum_payout: null,
              payout_profit_percentage: null,
              maximum_payout: null,
              maximum_payout_count: null,
              profit_split_trader_percent: null,
              profit_split_firm_percent: null,
              no_fixed_payout_window: false,
              payout_cycle_start_date: null,
              qualifying_days_since_last_payout: 0,
              payouts_completed: 0,
              preset_key: null,
              effective_date: null,
              source_note: "Custom rules entered during account creation.",
              scaling_tiers: [],
              rules_enabled_json: {
                profit_target: customProfitTarget !== "",
                max_loss: true,
                daily_loss_limit: customDailyLoss !== "",
                consistency: customConsistency !== "",
                minimum_trading_days: customMinimumDays !== "",
                qualifying_profit_days: false,
                payout_cycle_net_profit: false,
              },
              enabled: true,
            }),
          });
        }
      } else if (preset) {
        await api("/accounts/from-preset", {
          method: "POST",
          body: JSON.stringify({
            account: {
              name,
              external_account_id: externalId || null,
              provider: "tradovate",
              account_type:
                phase.toLowerCase() === "evaluation"
                  ? "evaluation"
                  : phase.toLowerCase() === "funded"
                    ? "funded"
                    : "simulated",
              starting_balance: preset.account_size,
              timezone: DEFAULT_TIMEZONE,
              currency: "USD",
            },
            preset: {
              preset_key: preset.preset_key,
              evaluation_drawdown_choice: requiresDrawdown ? drawdown || null : null,
              daily_loss_limit_enabled: requiresDll ? dll === "on" : null,
            },
          }),
        });
      }
      await onSaved();
      setStep(6);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Account could not be created.");
    } finally {
      setSaving(false);
    }
  }

  const providerLabel =
    plan === CUSTOM_PLAN
      ? "Manual / custom"
      : preset?.provider || planPresets[0]?.provider || "Preset catalog";

  return (
    <section className="card preset-wizard" aria-label="Create account">
      <div className="wizard-heading">
        <div>
          <p className="eyebrow">Add account</p>
          <h2>{step === 6 ? "Account created" : `Step ${step} of 5`}</h2>
        </div>
        <button className="button quiet" type="button" onClick={onCancel}>Close</button>
      </div>

      <ol className="wizard-steps" aria-label="Account creation steps">
        {["Plan", "Phase / type", "Account size", "Configuration", "Review"].map((label, index) => (
          <li className={step === index + 1 ? "active" : step > index + 1 ? "complete" : ""} key={label}>
            <span>{index + 1}</span>{label}
          </li>
        ))}
      </ol>

      {error && <ErrorState message={error} />}

      {step === 1 && (
        <div className="wizard-panel">
          <div className="field">
            <label htmlFor="preset_plan">Plan family</label>
            <select
              id="preset_plan"
              value={plan}
              onChange={(event) => choosePlan(event.target.value)}
              disabled={loadingPresets}
            >
              {loadingPresets && <option value="">Loading plans…</option>}
              {planOptions.map((item) => <option key={item} value={item}>{prettyPlan(item)}</option>)}
            </select>
          </div>
          <div className="field">
            <label htmlFor="preset_provider">Provider</label>
            <input id="preset_provider" value={providerLabel} readOnly />
          </div>
          <p className="wizard-help">
            Preset plans use the rules returned by JournalMe&apos;s preset catalog. Custom creates a normal account you can configure yourself.
          </p>
        </div>
      )}

      {step === 2 && (
        <div className="wizard-panel">
          {plan === CUSTOM_PLAN ? (
            <div className="field">
              <label htmlFor="custom_account_type">Account type</label>
              <select
                id="custom_account_type"
                value={customType}
                onChange={(event) => {
                  setCustomType(event.target.value);
                  setPhase(event.target.value);
                  setNameTouched(false);
                }}
              >
                <option value="evaluation">Evaluation</option>
                <option value="funded">Funded</option>
                <option value="simulated">Simulated</option>
                <option value="personal">Personal</option>
              </select>
            </div>
          ) : (
            <div className="field">
              <label htmlFor="preset_phase">Phase</label>
              <select
                id="preset_phase"
                value={phase}
                onChange={(event) => {
                  setPhase(event.target.value);
                  setNameTouched(false);
                }}
                disabled={phaseOptions.length <= 1}
              >
                {phaseOptions.map((item) => <option key={item} value={item}>{prettyPhase(item)}</option>)}
              </select>
              {phaseOptions.length === 1 && (
                <small className="field-hint">Only {prettyPhase(phaseOptions[0])} currently exists in the preset catalog for {prettyPlan(plan)}.</small>
              )}
            </div>
          )}
          {plan === "LucidDaily" && phase.toLowerCase() === "evaluation" && (
            <p className="callout">Evaluation drawdown and Daily Loss Limit are purchase choices and must be recorded explicitly.</p>
          )}
        </div>
      )}

      {step === 3 && (
        <div className="wizard-panel">
          {plan === CUSTOM_PLAN ? (
            <div className="field">
              <label htmlFor="custom_balance">Starting balance</label>
              <input
                id="custom_balance"
                inputMode="decimal"
                value={customBalance}
                onChange={(event) => {
                  setCustomBalance(event.target.value);
                  setNameTouched(false);
                }}
                placeholder="50000"
              />
              <small className="field-hint">Leave blank if the account does not have a meaningful starting balance.</small>
            </div>
          ) : (
            <div className="field">
              <label htmlFor="preset_size">Account size</label>
              <select
                id="preset_size"
                value={accountSize}
                onChange={(event) => {
                  setAccountSize(event.target.value);
                  setNameTouched(false);
                }}
                disabled={sizeOptions.length <= 1}
              >
                {sizeOptions.map((item) => <option key={item} value={item}>{money(item)}</option>)}
              </select>
              {preset && <small className="field-hint">{preset.display_name}</small>}
            </div>
          )}
        </div>
      )}

      {step === 4 && (
        <div className="wizard-panel plan-configuration">
          {plan === CUSTOM_PLAN ? (
            <div className="custom-account-config">
              <div className="form-grid custom-rules-grid">
                <div className="field">
                  <label htmlFor="custom_timezone">Timezone</label>
                  <select id="custom_timezone" value={customTimezone} onChange={(event) => setCustomTimezone(event.target.value)}>
                    <option value="America/New_York">Eastern · America/New_York</option>
                    <option value="America/Chicago">Central · America/Chicago</option>
                    <option value="America/Denver">Mountain · America/Denver</option>
                    <option value="America/Los_Angeles">Pacific · America/Los_Angeles</option>
                    <option value="UTC">UTC</option>
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="custom_firm">Firm / source</label>
                  <input id="custom_firm" value={customFirmName} onChange={(event) => setCustomFirmName(event.target.value)} placeholder="Custom" />
                </div>
                <div className="field">
                  <label htmlFor="custom_profit_target">Profit target <span className="muted">optional</span></label>
                  <input id="custom_profit_target" inputMode="decimal" value={customProfitTarget} onChange={(event) => setCustomProfitTarget(event.target.value)} placeholder="3000" />
                </div>
                <div className="field">
                  <label htmlFor="custom_max_loss">Maximum loss {customRulesRequested && <span className="required-mark">required</span>}</label>
                  <input id="custom_max_loss" inputMode="decimal" value={customMaxLoss} onChange={(event) => setCustomMaxLoss(event.target.value)} placeholder="2000" />
                </div>
                <div className="field">
                  <label htmlFor="custom_daily_loss">Daily loss limit <span className="muted">optional</span></label>
                  <input id="custom_daily_loss" inputMode="decimal" value={customDailyLoss} onChange={(event) => setCustomDailyLoss(event.target.value)} placeholder="1200" />
                </div>
                <div className="field">
                  <label htmlFor="custom_consistency">Consistency % <span className="muted">optional</span></label>
                  <input id="custom_consistency" inputMode="decimal" value={customConsistency} onChange={(event) => setCustomConsistency(event.target.value)} placeholder="50" />
                </div>
                <div className="field">
                  <label htmlFor="custom_min_days">Minimum trading days <span className="muted">optional</span></label>
                  <input id="custom_min_days" inputMode="numeric" value={customMinimumDays} onChange={(event) => setCustomMinimumDays(event.target.value)} placeholder="2" />
                </div>
                <div className="field">
                  <label htmlFor="custom_drawdown_type">Drawdown type <span className="muted">optional</span></label>
                  <select id="custom_drawdown_type" value={customDrawdownType} onChange={(event) => setCustomDrawdownType(event.target.value)}>
                    <option value="">Not set</option>
                    <option value="intraday_trailing">Intraday trailing</option>
                    <option value="end_of_day_trailing">End-of-Day trailing</option>
                    <option value="static">Static</option>
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="custom_drawdown_amount">Drawdown amount <span className="muted">optional</span></label>
                  <input id="custom_drawdown_amount" inputMode="decimal" value={customDrawdownAmount} onChange={(event) => setCustomDrawdownAmount(event.target.value)} placeholder="2000" />
                </div>
              </div>
              {!customRulesComplete && <p className="configuration-required">Maximum loss is required when you define a custom prop-rule profile.</p>}
              <p className="callout">Leave the optional rule fields blank for a plain account, or fill them in to create a custom prop profile immediately.</p>
            </div>
          ) : requiresDrawdown || requiresDll ? (
            <>
              {requiresDrawdown && (
                <fieldset>
                  <legend>Evaluation drawdown</legend>
                  <label><input type="radio" name="evaluation_drawdown" value="end_of_day_trailing" checked={drawdown === "end_of_day_trailing"} onChange={(event) => setDrawdown(event.target.value)} /> End-of-Day trailing</label>
                  <label><input type="radio" name="evaluation_drawdown" value="intraday_trailing" checked={drawdown === "intraday_trailing"} onChange={(event) => setDrawdown(event.target.value)} /> Intraday trailing</label>
                </fieldset>
              )}
              {requiresDll && (
                <fieldset>
                  <legend>Purchased Daily Loss Limit</legend>
                  <label><input type="radio" name="dll" value="on" checked={dll === "on"} onChange={(event) => setDll(event.target.value)} /> ON · fixed $1,200</label>
                  <label><input type="radio" name="dll" value="off" checked={dll === "off"} onChange={(event) => setDll(event.target.value)} /> OFF · Not applicable</label>
                </fieldset>
              )}
              {!configurationComplete && <p className="configuration-required">Configuration required. JournalMe will not guess these purchase choices.</p>}
            </>
          ) : (
            <div className="configuration-summary">
              <span className="status-dot ready" />
              <div>
                <strong>No additional purchase choices required.</strong>
                <p className="muted">The selected preset can be reviewed and saved as-is. You can edit the copied account profile later.</p>
              </div>
            </div>
          )}
        </div>
      )}

      {step === 5 && (
        <form onSubmit={save} className="wizard-panel preset-review">
          <div className="field">
            <label htmlFor="preset_account_name">Account display name</label>
            <input
              id="preset_account_name"
              value={name}
              onChange={(event) => {
                setName(event.target.value);
                setNameTouched(true);
              }}
              required
            />
          </div>
          {plan !== CUSTOM_PLAN && (
            <div className="field">
              <label htmlFor="preset_external_id">External Tradovate ID <span className="muted">optional</span></label>
              <input id="preset_external_id" value={externalId} onChange={(event) => setExternalId(event.target.value)} />
            </div>
          )}

          <dl>
            <div><dt>Plan</dt><dd>{plan === CUSTOM_PLAN ? "Custom" : preset?.display_name ?? prettyPlan(plan)}</dd></div>
            <div><dt>Phase / type</dt><dd>{plan === CUSTOM_PLAN ? prettyPhase(customType) : prettyPhase(phase)}</dd></div>
            <div><dt>Starting balance</dt><dd>{money(plan === CUSTOM_PLAN ? customBalance || null : preset?.account_size)}</dd></div>
            {plan !== CUSTOM_PLAN && preset && <div><dt>Maximum loss</dt><dd>{money(String(preset.rules.max_loss ?? ""))}</dd></div>}
            {requiresDll && <div><dt>DLL</dt><dd>{dll === "on" ? "$1,200.00" : dll === "off" ? "Not applicable" : "Not selected"}</dd></div>}
            {requiresDrawdown && <div><dt>Evaluation drawdown</dt><dd>{drawdown ? drawdown.replaceAll("_", " ") : "Not selected"}</dd></div>}
            {plan === CUSTOM_PLAN && <div><dt>Timezone</dt><dd>{customTimezone}</dd></div>}
            {plan === CUSTOM_PLAN && customRulesRequested && <div><dt>Firm / source</dt><dd>{customFirmName || "Custom"}</dd></div>}
            {plan === CUSTOM_PLAN && customRulesRequested && <div><dt>Maximum loss</dt><dd>{money(customMaxLoss)}</dd></div>}
            {plan === CUSTOM_PLAN && customProfitTarget && <div><dt>Profit target</dt><dd>{money(customProfitTarget)}</dd></div>}
          </dl>

          <p className="disclaimer">
            {plan === CUSTOM_PLAN
              ? "This creates a normal JournalMe account without attaching a firm preset."
              : "Preset values are copied into a user-editable, versioned profile. Verify them against your current firm agreement."}
          </p>
          <button className="button primary save-account-button" disabled={saving} aria-busy={saving}>
            {saving ? <><span className="button-spinner" /> Creating account…</> : "Create account"}
          </button>
        </form>
      )}

      {step === 6 && (
        <div className="wizard-panel success-panel">
          <div className="success-mark">✓</div>
          <div>
            <h3>Account created</h3>
            <p className="muted">It is ready in your JournalMe workspace.</p>
          </div>
          <button className="button primary" onClick={onCancel}>Done</button>
        </div>
      )}

      {step < 5 && (
        <footer className="wizard-actions">
          <button className="button" type="button" disabled={step === 1} onClick={() => setStep((value) => Math.max(1, value - 1))}>Back</button>
          <button className="button primary" type="button" onClick={next}>Continue</button>
        </footer>
      )}
    </section>
  );
}
