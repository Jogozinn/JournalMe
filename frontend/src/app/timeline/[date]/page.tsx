"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";

import { useAccount } from "@/components/account-provider";
import { EmptyState, ErrorState, PageHeader, Pnl, Skeleton } from "@/components/ui";
import { api, duration, money, percent, quantity, timeOnly } from "@/lib/api";
import type { Playbook, ReviewStatus, Trade } from "@/lib/types";

type Timeline = {
  trading_date: string;
  journal: Record<string, unknown> | null;
  trades: (Trade & { running_net_pnl: string; review: ReviewStatus })[];
  review: ReviewStatus;
  navigation: { previous: string | null; next: string | null };
  activity: {
    completed_trades: number;
    orders_submitted: number;
    orders_filled: number;
    orders_canceled: number;
    orders_rejected: number;
    orders_other: number;
    fill_count: number;
    contracts_executed: string;
    fees_paid: string | null;
    gross_pnl: string;
    net_pnl: string;
    fees_complete: boolean;
  };
  summary: {
    gross_pnl: string;
    fees: string | null;
    net_pnl: string;
    trade_count: number;
    win_rate: string | null;
    high_water_pnl: string;
    low_water_pnl: string;
    best_trade: Trade | null;
    worst_trade: Trade | null;
  };
};

const QUICK_RATINGS = [
  ["great", "Great"],
  ["good", "Good"],
  ["mixed", "Mixed"],
  ["bad", "Bad"],
] as const;

const QUICK_FOCUS = ["Followed plan", "Patience", "Entries", "Risk", "Exits", "Overtrading"];
const QUICK_EMOTIONS = ["Focused", "Calm", "Confident", "Frustrated", "Impatient", "Tired", "Anxious"];
const QUICK_BEHAVIORS = ["Chased", "FOMO", "Revenge traded", "Oversized", "Moved stop", "Exited early", "Good patience"];

export default function TimelinePage() {
  const { date } = useParams<{ date: string }>();
  const { account, loading } = useAccount();
  const [data, setData] = useState<Timeline | null>(null);
  const [error, setError] = useState("");
  const [playbooks, setPlaybooks] = useState<Playbook[]>([]);
  const [saving, setSaving] = useState(false);
  const [replay, setReplay] = useState(false);
  const [replayIndex, setReplayIndex] = useState(0);
  const [quickRating, setQuickRating] = useState("");
  const [quickFocus, setQuickFocus] = useState<string[]>([]);
  const [quickEmotions, setQuickEmotions] = useState<string[]>([]);
  const [quickBehaviors, setQuickBehaviors] = useState<string[]>([]);
  const [quickNote, setQuickNote] = useState("");
  const [quickFollowedRules, setQuickFollowedRules] = useState("");
  const [reviewDepth, setReviewDepth] = useState<"quick" | "deep">("quick");

  const load = () => {
    if (!account) return;
    Promise.all([
      api<Timeline>(`/timeline/${date}?account_id=${account.id}`),
      api<Playbook[]>("/playbooks?active=true"),
    ])
      .then(([timeline, nextPlaybooks]) => {
        setData(timeline);
        setPlaybooks(nextPlaybooks);
        setError("");
        setReplayIndex(0);
        const nextJournal = timeline.journal ?? {};
        setQuickRating(String(nextJournal.quick_rating ?? ""));
        setQuickFocus(Array.isArray(nextJournal.quick_focus_tags_json) ? nextJournal.quick_focus_tags_json as string[] : []);
        setQuickEmotions(Array.isArray(nextJournal.quick_emotion_tags_json) ? nextJournal.quick_emotion_tags_json as string[] : []);
        setQuickBehaviors(Array.isArray(nextJournal.quick_behavior_tags_json) ? nextJournal.quick_behavior_tags_json as string[] : []);
        setQuickNote(String(nextJournal.quick_note ?? ""));
        setQuickFollowedRules(nextJournal.followed_rules === null || nextJournal.followed_rules === undefined ? "" : String(nextJournal.followed_rules));
        setReviewDepth(nextJournal.review_depth === "deep" ? "deep" : "quick");
      })
      .catch((reason: Error) => setError(reason.message));
  };

  useEffect(load, [account, date]);

  function toggleQuickTag(value: string, current: string[], setter: (next: string[]) => void) {
    setter(current.includes(value) ? current.filter((item) => item !== value) : [...current, value]);
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!account) return;
    const form = new FormData(event.currentTarget);
    const value = (name: string) => String(form.get(name) || "") || null;
    setSaving(true);
    try {
      await api(`/journals/daily/${date}?account_id=${account.id}`, {
        method: "PUT",
        body: JSON.stringify({
          pre_session_mindset: value("pre_session_mindset"),
          pre_session_plan: value("pre_session_plan"),
          daily_bias: value("daily_bias"),
          important_events: value("important_events"),
          confidence_score: form.get("confidence_score") ? Number(form.get("confidence_score")) : null,
          sleep_quality: form.get("sleep_quality") ? Number(form.get("sleep_quality")) : null,
          energy_score: form.get("energy_score") ? Number(form.get("energy_score")) : null,
          daily_goal: form.get("daily_goal") || null,
          max_daily_loss: form.get("max_daily_loss") || null,
          max_trades: form.get("max_trades") ? Number(form.get("max_trades")) : null,
          allowed_playbook_ids: form.getAll("allowed_playbook_ids"),
          prohibited_behaviors: String(form.get("prohibited_behaviors") || "").split("\n").map((item) => item.trim()).filter(Boolean),
          checklist_json: String(form.get("checklist") || "").split("\n").map((text, index) => ({ text: text.trim(), complete: false, sort_order: index })).filter((item) => item.text),
          quick_rating: quickRating || null,
          quick_focus_tags_json: quickFocus,
          quick_emotion_tags_json: quickEmotions,
          quick_behavior_tags_json: quickBehaviors,
          quick_note: quickNote || null,
          review_depth: reviewDepth,
          day_grade: value("day_grade"),
          best_decision: value("best_decision"),
          biggest_mistake: value("biggest_mistake"),
          reflection: value("reflection"),
          what_worked: value("what_worked"),
          what_did_not_work: value("what_did_not_work"),
          lesson_learned: value("lesson_learned"),
          focus_for_next_session: value("focus_for_next_session"),
          followed_rules: quickFollowedRules === "" ? null : quickFollowedRules === "true",
          tomorrow_note: value("tomorrow_note"),
        }),
      });
      load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Daily journal could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  const visibleTrades = useMemo(() => {
    if (!data) return [];
    return replay ? data.trades.slice(0, replayIndex + 1) : data.trades;
  }, [data, replay, replayIndex]);

  if (loading) return <Skeleton rows={6} />;
  if (!account) return <EmptyState title="Create an account first." copy="Session stories belong to one trading account." href="/" action="Set up account" />;
  if (!data) return error ? <ErrorState message={error} /> : <Skeleton rows={6} />;

  const journal = data.journal ?? {};
  const prettyDate = new Date(`${date}T12:00:00`).toLocaleDateString([], {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
  });
  const replayTrade = data.trades[replayIndex] ?? null;

  return (
    <>
      <PageHeader
        eyebrow="Session story"
        title={prettyDate}
        description={`${data.summary.trade_count} trades · ${percent(data.summary.win_rate)} win rate`}
        action={<div className="review-nav">{data.navigation.previous ? <Link className="button" href={`/timeline/${data.navigation.previous}`}>‹ Previous day</Link> : <span />}<Link className="button" href="/calendar">Calendar</Link>{data.navigation.next && <Link className="button" href={`/timeline/${data.navigation.next}`}>Next day ›</Link>}</div>}
      />
      {error && <ErrorState message={error} />}

      <section className="session-summary premium-session-summary">
        <div><span>Net P&L</span><Pnl value={data.summary.net_pnl}>{money(data.summary.net_pnl)}</Pnl></div>
        <div><span>Gross P&L</span><strong>{money(data.summary.gross_pnl)}</strong></div>
        <div><span>Fees</span><strong>{money(data.summary.fees)}</strong></div>
        <div><span>High water</span><Pnl value={data.summary.high_water_pnl}>{money(data.summary.high_water_pnl)}</Pnl></div>
        <div><span>Low water</span><Pnl value={data.summary.low_water_pnl}>{money(data.summary.low_water_pnl)}</Pnl></div>
        <div><span>Best trade</span><Pnl value={data.summary.best_trade?.net_pnl ?? null}>{data.summary.best_trade ? money(data.summary.best_trade.net_pnl) : "Unavailable"}</Pnl></div>
        <div><span>Worst trade</span><Pnl value={data.summary.worst_trade?.net_pnl ?? null}>{data.summary.worst_trade ? money(data.summary.worst_trade.net_pnl) : "Unavailable"}</Pnl></div>
        <div><span>Journal</span><strong className={`status-text ${data.review.status}`}>{data.review.status}</strong></div>
      </section>

      <section className="card" style={{ marginBottom: "1rem" }}>
        <div className="section-title">
          <div>
            <p className="eyebrow">Execution ledger</p>
            <h2>What actually happened</h2>
          </div>
          <span>{data.activity.completed_trades} completed trades</span>
        </div>
        <div className="session-summary" style={{ marginTop: "0.75rem" }}>
          <div><span>Orders submitted</span><strong>{data.activity.orders_submitted}</strong></div>
          <div><span>Filled orders</span><strong>{data.activity.orders_filled}</strong></div>
          <div><span>Canceled</span><strong>{data.activity.orders_canceled}</strong></div>
          <div><span>Rejected</span><strong>{data.activity.orders_rejected}</strong></div>
          <div><span>Actual fills</span><strong>{data.activity.fill_count}</strong></div>
          <div><span>Contracts executed</span><strong>{quantity(data.activity.contracts_executed)}</strong></div>
          <div><span>Fees paid</span><strong>{money(data.activity.fees_paid)}</strong></div>
          <div><span>Net result</span><Pnl value={data.activity.net_pnl}>{money(data.activity.net_pnl)}</Pnl></div>
        </div>
        <p className="muted" style={{ marginTop: "0.75rem" }}>Canceled and rejected orders are activity, not trades. Partial fills and partial exits stay inside the same flat-to-flat trade.</p>
      </section>

      <section className="timeline-layout premium-timeline-layout">
        <div className="timeline-main">
          {data.trades.length > 1 && (
            <section className={`session-replay card ${replay ? "active" : ""}`}>
              <div className="replay-copy">
                <div className="replay-heading">
                  <span>Session replay</span>
                  {replay && <strong>{replayIndex + 1} of {data.trades.length}</strong>}
                </div>
                <h2>{replay && replayTrade ? `${replayTrade.symbol} ${String(replayTrade.side).toLowerCase()}` : "Replay the day in sequence"}</h2>
                <p>{replay && replayTrade ? `Running P&L ${money(replayTrade.running_net_pnl)} after this trade.` : "Move through each execution without changing the journal."}</p>
                <div className="replay-track" aria-label="Replay progress">
                  {data.trades.map((trade, index) => (
                    <button
                      key={trade.id}
                      type="button"
                      className={index < replayIndex ? "revealed" : index === replayIndex && replay ? "current" : ""}
                      aria-label={`Open ${trade.symbol} at ${timeOnly(trade.entry_timestamp)}`}
                      onClick={() => {
                        setReplay(true);
                        setReplayIndex(index);
                      }}
                    >
                      <span />
                    </button>
                  ))}
                </div>
              </div>
              <div className="replay-actions">
                {!replay ? (
                  <button className="button primary" type="button" onClick={() => { setReplay(true); setReplayIndex(0); }}>Start replay</button>
                ) : (
                  <>
                    <button className="button" type="button" disabled={replayIndex === 0} onClick={() => setReplayIndex((value) => Math.max(value - 1, 0))}>Previous</button>
                    <button className="button primary" type="button" disabled={replayIndex >= data.trades.length - 1} onClick={() => setReplayIndex((value) => Math.min(value + 1, data.trades.length - 1))}>Next trade</button>
                    <button className="button quiet" type="button" onClick={() => setReplay(false)}>Full day</button>
                  </>
                )}
              </div>
            </section>
          )}
          <div className="timeline-story">
          <article className="timeline-event pre-session card">
            <span className="timeline-dot" />
            <p className="eyebrow">Before the open</p>
            <h2>{String(journal.daily_bias ?? "Bias not recorded")}</h2>
            <p>{String(journal.pre_session_plan ?? "Add the plan you intended to follow.")}</p>
            {Boolean(journal.pre_session_mindset) && <blockquote>{String(journal.pre_session_mindset)}</blockquote>}
          </article>
          {visibleTrades.map((trade) => (
            <Link href={`/trades/${trade.id}`} className={`timeline-event trade-event card ${replay && trade.id === replayTrade?.id ? "replay-current" : ""}`} key={trade.id}>
              <span className="timeline-dot" />
              <div className="event-time">
                <strong>{timeOnly(trade.entry_timestamp)}</strong>
                <span>to {timeOnly(trade.exit_timestamp)}</span>
              </div>
              <div className="event-main">
                <div><strong>{trade.symbol}</strong><span className={`side-token ${trade.side}`}>{trade.side}</span></div>
                <p>{quantity(trade.quantity, true)} · {duration(trade.duration_seconds)} · <span className={`status-text ${trade.review.status}`}>{trade.review.status}</span></p>
              </div>
              <div className="event-result">
                <Pnl value={trade.net_pnl}>{money(trade.net_pnl)}</Pnl>
                <small>Running {money(trade.running_net_pnl)}</small>
              </div>
            </Link>
          ))}
          {!replay && (
            <article className="timeline-event card closing-event">
              <span className="timeline-dot" />
              <p className="eyebrow">Closing reflection</p>
              <h2>{String(journal.day_grade ? `Day grade · ${journal.day_grade}` : "Reflection not finished")}</h2>
              <p>{String(journal.reflection ?? "Close the loop on this session.")}</p>
            </article>
          )}
          </div>
        </div>

        <form className="card daily-journal-form premium-journal-form" onSubmit={save}>
          <div className="journal-form-head"><p className="eyebrow">Daily review · {account.timezone}</p><h2>Check in first. Add detail only when it helps.</h2><p className="completion-note">{data.review.missing.length ? `Still needed: ${data.review.missing.join(" · ")}` : "Daily review complete."}</p></div>

          <section className="quick-review-panel" aria-label="Quick daily review">
            <div className="quick-review-mode">
              <button className={reviewDepth === "quick" ? "active" : ""} type="button" onClick={() => setReviewDepth("quick")}>Quick review</button>
              <button className={reviewDepth === "deep" ? "active" : ""} type="button" onClick={() => setReviewDepth("deep")}>Deep review</button>
            </div>
            <div className="quick-review-question">
              <span>How was your trading today?</span>
              <div className="quick-choice-row">{QUICK_RATINGS.map(([value, label]) => <button key={value} className={quickRating === value ? "selected" : ""} type="button" onClick={() => setQuickRating(value)}>{label}</button>)}</div>
            </div>
            <div className="quick-review-question">
              <span>Did you follow your rules?</span>
              <div className="quick-choice-row"><button className={quickFollowedRules === "true" ? "selected" : ""} type="button" onClick={() => setQuickFollowedRules("true")}>Yes</button><button className={quickFollowedRules === "false" ? "selected" : ""} type="button" onClick={() => setQuickFollowedRules("false")}>No</button></div>
            </div>
            <div className="quick-review-question">
              <span>What mattered most?</span>
              <div className="quick-chip-row">{QUICK_FOCUS.map((item) => <button key={item} className={quickFocus.includes(item) ? "selected" : ""} type="button" onClick={() => toggleQuickTag(item, quickFocus, setQuickFocus)}>{item}</button>)}</div>
            </div>
            <div className="quick-review-question">
              <span>How did you feel?</span>
              <div className="quick-chip-row">{QUICK_EMOTIONS.map((item) => <button key={item} className={quickEmotions.includes(item) ? "selected" : ""} type="button" onClick={() => toggleQuickTag(item, quickEmotions, setQuickEmotions)}>{item}</button>)}</div>
            </div>
            <div className="quick-review-question">
              <span>Anything JournalMe should remember?</span>
              <div className="quick-chip-row">{QUICK_BEHAVIORS.map((item) => <button key={item} className={quickBehaviors.includes(item) ? "selected" : ""} type="button" onClick={() => toggleQuickTag(item, quickBehaviors, setQuickBehaviors)}>{item}</button>)}</div>
              <input className="quick-note-input" value={quickNote} onChange={(event) => setQuickNote(event.target.value)} placeholder="Optional note" />
            </div>
          </section>

          <details className="journal-section" open={reviewDepth === "deep" && data.trades.length === 0}>
            <summary><span>Before the session</span><small>Mindset, plan, bias, context</small></summary>
            <div className="journal-section-body">
              <div className="field"><label htmlFor="pre_session_mindset">Pre-session mindset</label><textarea id="pre_session_mindset" name="pre_session_mindset" defaultValue={String(journal.pre_session_mindset ?? "")} /></div>
              <div className="field"><label htmlFor="pre_session_plan">Plan</label><textarea id="pre_session_plan" name="pre_session_plan" defaultValue={String(journal.pre_session_plan ?? "")} /></div>
              <div className="field"><label htmlFor="daily_bias">Daily bias</label><input id="daily_bias" name="daily_bias" defaultValue={String(journal.daily_bias ?? "")} /></div>
              <div className="field"><label htmlFor="important_events">Important events</label><input id="important_events" name="important_events" defaultValue={String(journal.important_events ?? "")} /></div>
              <div className="score-row">{[["confidence_score", "Confidence"], ["sleep_quality", "Sleep"], ["energy_score", "Energy"]].map(([name, label]) => <div className="field" key={name}><label htmlFor={name}>{label}</label><select id={name} name={name} defaultValue={String(journal[name] ?? "")}><option value="">Not set</option>{[1, 2, 3, 4, 5].map((score) => <option key={score}>{score}</option>)}</select></div>)}</div>
            </div>
          </details>

          <details className="journal-section">
            <summary><span>Guardrails</span><small>Limits, playbooks, behaviors</small></summary>
            <div className="journal-section-body">
              <div className="score-row"><div className="field"><label htmlFor="daily_goal">Daily goal</label><input id="daily_goal" name="daily_goal" inputMode="decimal" defaultValue={String(journal.daily_goal ?? "")} /></div><div className="field"><label htmlFor="max_daily_loss">Maximum loss</label><input id="max_daily_loss" name="max_daily_loss" inputMode="decimal" defaultValue={String(journal.max_daily_loss ?? "")} /></div><div className="field"><label htmlFor="max_trades">Maximum trades</label><input id="max_trades" name="max_trades" type="number" min="1" defaultValue={String(journal.max_trades ?? "")} /></div></div>
              <fieldset className="day-playbooks"><legend>Allowed playbooks</legend>{playbooks.map((item) => <label key={item.id}><input type="checkbox" name="allowed_playbook_ids" value={item.id} defaultChecked={Array.isArray(journal.allowed_playbook_ids) && (journal.allowed_playbook_ids as unknown as string[]).includes(item.id)} /> {item.name}</label>)}</fieldset>
              <div className="field"><label htmlFor="prohibited_behaviors">Prohibited behaviors, one per line</label><textarea id="prohibited_behaviors" name="prohibited_behaviors" defaultValue={Array.isArray(journal.prohibited_behaviors) ? (journal.prohibited_behaviors as unknown as string[]).join("\n") : ""} /></div>
              <div className="field"><label htmlFor="checklist">Custom checklist, one item per line</label><textarea id="checklist" name="checklist" defaultValue={Array.isArray(journal.checklist_json) ? (journal.checklist_json as unknown as { text: string }[]).map((item) => item.text).join("\n") : ""} /></div>
            </div>
          </details>

          <details className="journal-section" open={reviewDepth === "deep" && data.trades.length > 0}>
            <summary><span>After the session</span><small>Decisions, mistakes, lessons</small></summary>
            <div className="journal-section-body">
              <div className="field"><label htmlFor="best_decision">Best decision</label><textarea id="best_decision" name="best_decision" defaultValue={String(journal.best_decision ?? "")} /></div>
              <div className="field"><label htmlFor="biggest_mistake">Biggest mistake</label><textarea id="biggest_mistake" name="biggest_mistake" defaultValue={String(journal.biggest_mistake ?? "")} /></div>
              <div className="field"><label htmlFor="what_worked">What worked</label><textarea id="what_worked" name="what_worked" defaultValue={String(journal.what_worked ?? "")} /></div>
              <div className="field"><label htmlFor="what_did_not_work">What did not work</label><textarea id="what_did_not_work" name="what_did_not_work" defaultValue={String(journal.what_did_not_work ?? "")} /></div>
              <div className="field"><label htmlFor="lesson_learned">Lesson learned</label><textarea id="lesson_learned" name="lesson_learned" defaultValue={String(journal.lesson_learned ?? "")} /></div>
              <div className="field"><label htmlFor="reflection">Reflection</label><textarea id="reflection" name="reflection" defaultValue={String(journal.reflection ?? "")} /></div>
              <div className="field"><label htmlFor="focus_for_next_session">Focus for next session</label><textarea id="focus_for_next_session" name="focus_for_next_session" defaultValue={String(journal.focus_for_next_session ?? "")} /></div>
              <div className="field"><label htmlFor="tomorrow_note">Tomorrow note</label><textarea id="tomorrow_note" name="tomorrow_note" defaultValue={String(journal.tomorrow_note ?? "")} /></div>
              <div className="score-row"><div className="field"><label htmlFor="followed_rules">Followed daily rules</label><select id="followed_rules" name="followed_rules" value={quickFollowedRules} onChange={(event) => setQuickFollowedRules(event.target.value)}><option value="">Not answered</option><option value="true">Yes</option><option value="false">No</option></select></div><div className="field"><label htmlFor="day_grade">Day grade</label><select id="day_grade" name="day_grade" defaultValue={String(journal.day_grade ?? "")}><option value="">Not graded</option>{["A+", "A", "B", "C", "D", "F"].map((grade) => <option key={grade}>{grade}</option>)}</select></div></div>
            </div>
          </details>

          <div className="journal-save-bar">
            <button className="button primary" disabled={saving}>{saving ? "Saving..." : "Save daily journal"}</button>
            <div className="period-links"><Link href={`/reviews/weekly/${date}`}>Week review</Link><Link href={`/reviews/monthly/${date.slice(0, 7)}-01`}>Month review</Link></div>
          </div>
        </form>
      </section>
    </>
  );
}
