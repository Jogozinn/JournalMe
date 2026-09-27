"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { useAccount } from "@/components/account-provider";
import { ErrorState, PageHeader, Pnl, Skeleton } from "@/components/ui";
import { api, money, percent } from "@/lib/api";
import type { Account } from "@/lib/types";

type Metrics = {
  trades: number;
  net_pnl: string;
  expectancy: string | null;
  win_rate: string | null;
  average_size: string | null;
};

type Insight = {
  key: string;
  title: string;
  evidence: "insufficient" | "early_signal" | "repeated_pattern" | "strong_evidence";
  evidence_score: number;
  explanation: string;
  difference_in_expectancy: string;
  condition: Metrics & { label: string };
  comparison: Metrics & { label: string };
};

type IntelligenceOverview = {
  selected_account_ids: string[];
  summary: Metrics;
  coverage: {
    accounts: number;
    trading_days: number;
    journal_days: number;
    quick_review_days: number;
    mindset_days: number;
    psychology_scope: "objective_only" | "objective_plus_limited_journal" | "objective_plus_mindset";
  };
  accounts: Array<{
    id: string;
    name: string;
    provider: string;
    account_type: string;
    lifecycle_status: string;
    active: boolean;
    include_in_learning: boolean;
    metrics: Metrics;
    coverage: {
      trading_days: number;
      journal_days: number;
      quick_review_days: number;
      mindset_days: number;
      journal_percent: number;
    };
  }>;
  current_vs_history: null | {
    current_account_id: string;
    current: Metrics;
    history: Metrics;
  };
  insights: Insight[];
  mindset_insights: Array<{
    key: string;
    category: string;
    tag: string;
    title: string;
    evidence: Insight["evidence"];
    evidence_score: number;
    explanation: string;
    difference_in_average_day_pnl: string;
    tagged: { days: number; average_day_pnl: string; positive_day_rate: string };
    other_reviewed_days: { days: number; average_day_pnl: string; positive_day_rate: string };
  }>;
};

const evidenceLabel: Record<Insight["evidence"], string> = {
  insufficient: "Insufficient data",
  early_signal: "Early signal",
  repeated_pattern: "Repeated pattern",
  strong_evidence: "Strong evidence",
};

function metricValue(value: string | null, kind: "money" | "percent" = "money") {
  if (kind === "percent") return percent(value);
  return money(value);
}

export default function IntelligencePage() {
  const { account: currentAccount } = useAccount();
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [overview, setOverview] = useState<IntelligenceOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const loadAccounts = useCallback(async () => {
    const items = await api<Account[]>("/accounts?include_archived=true");
    setAccounts(items);
    setSelected(items.filter((item) => item.include_in_learning).map((item) => item.id));
    return items;
  }, []);

  useEffect(() => {
    loadAccounts()
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false));
  }, [loadAccounts]);

  useEffect(() => {
    if (!selected.length) {
      setOverview(null);
      return;
    }
    const params = new URLSearchParams();
    selected.forEach((id) => params.append("account_ids", id));
    if (currentAccount && selected.includes(currentAccount.id)) {
      params.set("current_account_id", currentAccount.id);
    }
    setLoading(true);
    api<IntelligenceOverview>(`/intelligence/overview?${params.toString()}`)
      .then((next) => {
        setOverview(next);
        setError("");
      })
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false));
  }, [currentAccount, selected]);

  const defaultIds = useMemo(
    () => accounts.filter((item) => item.include_in_learning).map((item) => item.id),
    [accounts],
  );

  async function saveLearningSet() {
    setSaving(true);
    setError("");
    try {
      await Promise.all(
        accounts.map((item) =>
          api(`/accounts/${item.id}`, {
            method: "PATCH",
            body: JSON.stringify({ include_in_learning: selected.includes(item.id) }),
          }),
        ),
      );
      await loadAccounts();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Learning scope could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  function toggle(id: string) {
    setSelected((current) =>
      current.includes(id) ? current.filter((item) => item !== id) : [...current, id],
    );
  }

  if (loading && !accounts.length) return <Skeleton rows={8} />;

  return (
    <div className="intelligence-page">
      <PageHeader
        eyebrow="Trader intelligence"
        title="Learn across your whole trading history"
        description="Choose the accounts that represent you. JournalMe keeps objective performance separate from mindset evidence when older accounts have less journal data."
      />
      {error && <ErrorState message={error} />}

      <section className="card learning-scope-card">
        <div className="section-title intelligence-section-title">
          <div>
            <p className="eyebrow">Learning scope</p>
            <h2>{selected.length} account{selected.length === 1 ? "" : "s"} selected</h2>
          </div>
          <div className="scope-actions">
            {currentAccount && (
              <button className="button quiet compact" type="button" onClick={() => setSelected([currentAccount.id])}>
                Current only
              </button>
            )}
            <button className="button quiet compact" type="button" onClick={() => setSelected(defaultIds)}>
              Default set
            </button>
            <button className="button quiet compact" type="button" onClick={() => setSelected(accounts.map((item) => item.id))}>
              All accounts
            </button>
          </div>
        </div>
        <div className="learning-account-grid">
          {accounts.map((item) => (
            <label key={item.id} className={`learning-account-option ${selected.includes(item.id) ? "selected" : ""}`}>
              <input type="checkbox" checked={selected.includes(item.id)} onChange={() => toggle(item.id)} />
              <span>
                <strong>{item.name}</strong>
                <small>{item.provider} · {item.lifecycle_status} · {item.active ? "active" : "archived"}</small>
              </span>
              {item.id === currentAccount?.id && <em>Current</em>}
            </label>
          ))}
        </div>
        <div className="learning-scope-footer">
          <p className="muted small">Analysis changes immediately. Saving makes this selection the default for future intelligence runs.</p>
          <button className="button primary compact" type="button" disabled={saving || !selected.length} onClick={() => void saveLearningSet()}>
            {saving ? "Saving…" : "Save learning set"}
          </button>
        </div>
      </section>

      {!selected.length ? (
        <section className="card compact-empty"><div><h3>Choose at least one account</h3><p className="muted">Archived accounts can stay in your learning history even when they are no longer part of the active workspace.</p></div></section>
      ) : loading || !overview ? (
        <Skeleton rows={8} />
      ) : (
        <>
          <section className="intelligence-summary-grid">
            <article className="card intelligence-stat"><span>Trades studied</span><strong>{overview.summary.trades}</strong></article>
            <article className="card intelligence-stat"><span>Net P&amp;L</span><Pnl value={overview.summary.net_pnl}><strong>{money(overview.summary.net_pnl)}</strong></Pnl></article>
            <article className="card intelligence-stat"><span>Expectancy</span><Pnl value={overview.summary.expectancy}><strong>{money(overview.summary.expectancy)}</strong></Pnl></article>
            <article className="card intelligence-stat"><span>Trading days</span><strong>{overview.coverage.trading_days}</strong></article>
            <article className="card intelligence-stat"><span>Journal days</span><strong>{overview.coverage.journal_days}</strong></article>
            <article className="card intelligence-stat"><span>Mindset days</span><strong>{overview.coverage.mindset_days}</strong></article>
          </section>

          <section className="card intelligence-coverage-card">
            <div>
              <p className="eyebrow">Evidence coverage</p>
              <h2>{overview.coverage.psychology_scope === "objective_only" ? "Objective history" : overview.coverage.psychology_scope === "objective_plus_mindset" ? "Objective + mindset history" : "Objective + limited journal history"}</h2>
            </div>
            <p>
              Older accounts can contribute fills, timing, size, P&amp;L and sequence patterns even when they have no journal. Psychology findings are only computed from periods where JournalMe actually has mindset context.
            </p>
          </section>

          {overview.current_vs_history && overview.current_vs_history.history.trades > 0 && (
            <section className="card current-history-card">
              <div className="section-title intelligence-section-title"><div><p className="eyebrow">Current vs history</p><h2>How the present account compares</h2></div></div>
              <div className="current-history-grid">
                <div><span>Current expectancy</span><Pnl value={overview.current_vs_history.current.expectancy}><strong>{money(overview.current_vs_history.current.expectancy)}</strong></Pnl><small>{overview.current_vs_history.current.trades} trades</small></div>
                <div><span>Historical expectancy</span><Pnl value={overview.current_vs_history.history.expectancy}><strong>{money(overview.current_vs_history.history.expectancy)}</strong></Pnl><small>{overview.current_vs_history.history.trades} trades</small></div>
                <div><span>Current win rate</span><strong>{percent(overview.current_vs_history.current.win_rate)}</strong></div>
                <div><span>Historical win rate</span><strong>{percent(overview.current_vs_history.history.win_rate)}</strong></div>
              </div>
            </section>
          )}

          <section className="intelligence-findings-section">
            <div className="section-title intelligence-section-title">
              <div><p className="eyebrow">Pattern engine</p><h2>What is repeating</h2></div>
              <span>{overview.insights.length} comparisons</span>
            </div>
            {!overview.insights.length ? (
              <div className="card compact-empty"><div><h3>Not enough history yet</h3><p className="muted">JournalMe will surface comparisons as the selected accounts accumulate enough repeated situations.</p></div></div>
            ) : (
              <div className="intelligence-findings-grid">
                {overview.insights.map((insight) => (
                  <article className="card intelligence-finding" key={insight.key}>
                    <header>
                      <span className={`evidence-badge ${insight.evidence}`}>{evidenceLabel[insight.evidence]}</span>
                      <small>{insight.evidence_score}/100 evidence</small>
                    </header>
                    <h3>{insight.title}</h3>
                    <p>{insight.explanation}</p>
                    <div className="insight-comparison-grid">
                      <div><span>{insight.condition.label}</span><strong>{metricValue(insight.condition.expectancy)}</strong><small>{insight.condition.trades} trades · {metricValue(insight.condition.win_rate, "percent")} wins</small></div>
                      <div><span>{insight.comparison.label}</span><strong>{metricValue(insight.comparison.expectancy)}</strong><small>{insight.comparison.trades} trades · {metricValue(insight.comparison.win_rate, "percent")} wins</small></div>
                    </div>
                    <footer>Expectancy difference <Pnl value={insight.difference_in_expectancy}>{money(insight.difference_in_expectancy)}</Pnl></footer>
                  </article>
                ))}
              </div>
            )}
          </section>

          {overview.mindset_insights.length > 0 && (
            <section className="intelligence-findings-section">
              <div className="section-title intelligence-section-title">
                <div><p className="eyebrow">Mindset & behavior</p><h2>What your check-ins are starting to reveal</h2></div>
                <span>{overview.coverage.mindset_days} mindset days</span>
              </div>
              <div className="intelligence-findings-grid">
                {overview.mindset_insights.map((insight) => (
                  <article className="card intelligence-finding" key={insight.key}>
                    <header><span className={`evidence-badge ${insight.evidence}`}>{evidenceLabel[insight.evidence]}</span><small>{insight.category}</small></header>
                    <h3>{insight.title}</h3>
                    <p>{insight.explanation}</p>
                    <div className="insight-comparison-grid">
                      <div><span>{insight.tag}</span><strong>{money(insight.tagged.average_day_pnl)}</strong><small>{insight.tagged.days} days · {percent(insight.tagged.positive_day_rate)} positive</small></div>
                      <div><span>Other reviewed days</span><strong>{money(insight.other_reviewed_days.average_day_pnl)}</strong><small>{insight.other_reviewed_days.days} days · {percent(insight.other_reviewed_days.positive_day_rate)} positive</small></div>
                    </div>
                    <footer>Average day difference <Pnl value={insight.difference_in_average_day_pnl}>{money(insight.difference_in_average_day_pnl)}</Pnl></footer>
                  </article>
                ))}
              </div>
            </section>
          )}

          <section className="account-learning-breakdown">
            <div className="section-title intelligence-section-title"><div><p className="eyebrow">Account chapters</p><h2>What each account contributes</h2></div></div>
            <div className="learning-breakdown-grid">
              {overview.accounts.map((item) => (
                <article className="card" key={item.id}>
                  <div><strong>{item.name}</strong><span>{item.provider} · {item.lifecycle_status}</span></div>
                  <dl>
                    <div><dt>Trades</dt><dd>{item.metrics.trades}</dd></div>
                    <div><dt>Expectancy</dt><dd>{money(item.metrics.expectancy)}</dd></div>
                    <div><dt>Journal</dt><dd>{item.coverage.journal_percent}%</dd></div>
                    <div><dt>Mindset days</dt><dd>{item.coverage.mindset_days}</dd></div>
                  </dl>
                </article>
              ))}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
