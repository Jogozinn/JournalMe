"use client";

import Link from "next/link";
import { FormEvent, Fragment, useEffect, useMemo, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";

import { Icon } from "@/components/icons";
import { AuthenticatedImage } from "@/components/authenticated-assets";
import { ErrorState, PageHeader, Pnl, Skeleton } from "@/components/ui";
import { api, dateTime, duration, money, price, quantity, timeOnly } from "@/lib/api";
import type { Playbook, ReviewStatus, Tag, Trade } from "@/lib/types";

type TradeDetail = Trade & {
  product: string | null;
  product_description: string | null;
  source_quality: string;
  reconciliation_warnings: string[];
  journal: Record<string, string | number | boolean | null> | null;
  previous_trade_id: string | null;
  next_trade_id: string | null;
  review_position: {
    index: number;
    count: number;
    date: string;
    date_mode: "trading" | "calendar";
  };
};

type Executions = {
  fills: {
    id: string;
    action: string;
    quantity: string;
    price: string;
    commission: string | null;
    timestamp: string;
  }[];
  orders: {
    id: string;
    type: string | null;
    status: string;
    limit_price: string | null;
    stop_price: string | null;
  }[];
};

type Screenshot = {
  id: string;
  filename: string;
  caption: string | null;
  content_url: string;
};

type CompanionCapture = {
  id: string;
  episode_id?: string | null;
  matched_trade_id: string | null;
  screenshot_url: string | null;
  has_screenshot?: boolean;
  captured_at: string;
  event_type: string;
  phase?: string | null;
  recorded_live?: boolean;
  match_status: string;
  note: string | null;
  setup_tags: string[];
  execution_tags: string[];
  emotion_tags: string[];
};

type PlaybookContext = {
  assignments: (Playbook & { is_primary: boolean })[];
  responses: { checklist_item_id: string; passed: boolean | null; note: string | null }[];
  violations: { id: string; rule_text: string; severity: string }[];
  review: ReviewStatus;
};

type TradeSequenceMember = {
  trade: Trade;
  note: string | null;
  sort_order: number;
  review: ReviewStatus | null;
};

type TradeSequence = {
  id: string;
  account_id: string;
  title: string | null;
  thesis: string | null;
  shared_context: string | null;
  lesson_learned: string | null;
  summary: {
    trade_count: number;
    net_pnl: string;
    gross_pnl: string;
    fees: string | null;
    started_at: string | null;
    ended_at: string | null;
    trading_dates: string[];
  };
  members: TradeSequenceMember[];
};

type SequenceCandidate = Trade & { sequence_id: string | null };

type SequenceCandidates = {
  date: string;
  date_mode: "trading" | "calendar";
  items: SequenceCandidate[];
};

export default function TradeReviewPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const dateMode = searchParams.get("date_mode") === "calendar" ? "calendar" : "trading";
  const navSuffix = dateMode === "calendar" ? "?date_mode=calendar" : "";
  const [trade, setTrade] = useState<TradeDetail | null>(null);
  const [executions, setExecutions] = useState<Executions | null>(null);
  const [screenshots, setScreenshots] = useState<Screenshot[]>([]);
  const [companionCaptures, setCompanionCaptures] = useState<CompanionCapture[]>([]);
  const [captureActionId, setCaptureActionId] = useState<string | null>(null);
  const [tags, setTags] = useState<Tag[]>([]);
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [playbooks, setPlaybooks] = useState<Playbook[]>([]);
  const [primaryPlaybook, setPrimaryPlaybook] = useState("");
  const [checklistResponses, setChecklistResponses] = useState<Record<string, boolean | null>>({});
  const [context, setContext] = useState<PlaybookContext | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  const [viewer, setViewer] = useState<{ path: string; alt: string; captureId?: string } | null>(null);
  const [sequence, setSequence] = useState<TradeSequence | null>(null);
  const [sequenceCandidates, setSequenceCandidates] = useState<SequenceCandidates | null>(null);
  const [sequencePickerOpen, setSequencePickerOpen] = useState(false);
  const [sequenceSelected, setSequenceSelected] = useState<string[]>([]);
  const [sequenceNotes, setSequenceNotes] = useState<Record<string, string>>( {} );
  const [sequenceTitle, setSequenceTitle] = useState("");
  const [sequenceThesis, setSequenceThesis] = useState("");
  const [sequenceContext, setSequenceContext] = useState("");
  const [sequenceLesson, setSequenceLesson] = useState("");
  const [sequenceSaving, setSequenceSaving] = useState(false);
  const [sequenceDirty, setSequenceDirty] = useState(false);

  useEffect(() => {
    Promise.all([
      api<TradeDetail>(`/trades/${params.id}?date_mode=${dateMode}`),
      api<Executions>(`/trades/${params.id}/executions`),
      api<Tag[]>("/tags"),
      api<Screenshot[]>(`/trades/${params.id}/attachments`),
      api<Playbook[]>("/playbooks?active=true"),
      api<PlaybookContext>(`/trades/${params.id}/playbooks`),
      api<CompanionCapture[]>("/captures?limit=100"),
      api<TradeSequence | null>(`/trades/${params.id}/sequence`),
      api<SequenceCandidates>(`/trades/${params.id}/sequence-candidates?date_mode=${dateMode}`),
    ])
      .then(([nextTrade, nextExecutions, nextTags, nextScreenshots, nextPlaybooks, nextContext, nextCaptures, nextSequence, nextCandidates]) => {
        setTrade(nextTrade);
        setExecutions(nextExecutions);
        setTags(nextTags);
        setScreenshots(nextScreenshots);
        setCompanionCaptures(
          nextCaptures.filter(
            (capture) =>
              capture.matched_trade_id === params.id &&
              ["matched", "suggested"].includes(capture.match_status),
          ),
        );
        setSelectedTags(nextTrade.tags.map((tag) => tag.id));
        setPlaybooks(nextPlaybooks);
        setContext(nextContext);
        setPrimaryPlaybook(nextContext.assignments.find((item) => item.is_primary)?.id ?? "");
        setChecklistResponses(Object.fromEntries(nextContext.responses.map((row) => [row.checklist_item_id, row.passed])));
        setSequence(nextSequence);
        setSequenceCandidates(nextCandidates);
        const selectedIds = nextSequence?.members.map((member) => member.trade.id) ?? [params.id];
        setSequenceSelected(selectedIds);
        setSequenceNotes(Object.fromEntries((nextSequence?.members ?? []).map((member) => [member.trade.id, member.note ?? ""])));
        setSequenceTitle(nextSequence?.title ?? "");
        setSequenceThesis(nextSequence?.thesis ?? "");
        setSequenceContext(nextSequence?.shared_context ?? "");
        setSequenceLesson(nextSequence?.lesson_learned ?? "");
        setSequenceDirty(false);
        setSequencePickerOpen(false);
      })
      .catch((reason: Error) => setError(reason.message));
  }, [params.id, dateMode]);

  useEffect(() => {
    const saveShortcut = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        document.querySelector<HTMLFormElement>("#trade-review-form")?.requestSubmit();
      }
    };
    window.addEventListener("keydown", saveShortcut);
    return () => window.removeEventListener("keydown", saveShortcut);
  }, []);

  useEffect(() => {
    if (!viewer) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const closeViewer = (event: KeyboardEvent) => {
      if (event.key === "Escape") setViewer(null);
    };
    window.addEventListener("keydown", closeViewer);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeViewer);
    };
  }, [viewer]);

  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (dirty || sequenceDirty) event.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty, sequenceDirty]);

  const groupedTags = useMemo(
    () =>
      Object.groupBy?.(tags, (tag) => tag.category) ??
      tags.reduce<Record<string, Tag[]>>((groups, tag) => {
        (groups[tag.category] ??= []).push(tag);
        return groups;
      }, {}),
    [tags],
  );

  async function persistSequence(): Promise<TradeSequence | null> {
    if (!trade || sequenceSelected.length < 2) return sequence;
    const body = {
      account_id: trade.account_id,
      title: sequenceTitle.trim() || null,
      thesis: sequenceThesis.trim() || null,
      shared_context: sequenceContext.trim() || null,
      lesson_learned: sequenceLesson.trim() || null,
      members: sequenceSelected.map((tradeId) => ({
        trade_id: tradeId,
        note: sequenceNotes[tradeId]?.trim() || null,
      })),
    };
    const nextSequence = await api<TradeSequence>(
      sequence ? `/trade-sequences/${sequence.id}` : "/trade-sequences",
      { method: sequence ? "PUT" : "POST", body: JSON.stringify(body) },
    );
    setSequence(nextSequence);
    setSequenceSelected(nextSequence.members.map((member) => member.trade.id));
    setSequenceNotes(Object.fromEntries(nextSequence.members.map((member) => [member.trade.id, member.note ?? ""])));
    setSequenceDirty(false);
    setSequencePickerOpen(false);
    setSequenceCandidates(
      await api<SequenceCandidates>(`/trades/${params.id}/sequence-candidates?date_mode=${dateMode}`),
    );
    return nextSequence;
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const submitter = (event.nativeEvent as SubmitEvent).submitter as HTMLButtonElement | null;
    const advance = submitter?.dataset.advance === "true";
    const form = new FormData(event.currentTarget);
    setSaving(true);
    setError("");
    const text = (name: string) => String(form.get(name) || "") || null;
    try {
      if (sequenceDirty && sequenceSelected.length > 1) {
        await persistSequence();
      }
      const updated = await api<TradeDetail>(`/trades/${params.id}/journal?date_mode=${dateMode}`, {
        method: "PUT",
        body: JSON.stringify({
          thesis: text("thesis"),
          entry_reason: text("entry_reason"),
          exit_reason: text("exit_reason"),
          what_went_well: text("what_went_well"),
          what_went_wrong: text("what_went_wrong"),
          lesson_learned: text("lesson_learned"),
          best_decision: text("best_decision"),
          worst_decision: text("worst_decision"),
          confidence_score: form.get("confidence_score") ? Number(form.get("confidence_score")) : null,
          discipline_score: form.get("discipline_score") ? Number(form.get("discipline_score")) : null,
          patience_score: form.get("patience_score") ? Number(form.get("patience_score")) : null,
          trade_grade: text("trade_grade"),
          followed_plan:
            form.get("followed_plan") === ""
              ? null
              : form.get("followed_plan") === "true",
          pre_trade_emotion: text("pre_trade_emotion"),
          post_trade_emotion: text("post_trade_emotion"),
          market_condition: text("market_condition"),
          session_name: text("session_name"),
          custom_notes: text("custom_notes"),
          mark_reviewed: true,
          tag_ids: selectedTags,
        }),
      });
      await api(`/trades/${params.id}/playbooks`, {
        method: "PUT",
        body: JSON.stringify({ primary_playbook_id: primaryPlaybook || null, secondary_playbook_ids: [] }),
      });
      const selectedPlan = playbooks.find((item) => item.id === primaryPlaybook);
      if (selectedPlan?.checklist_items.length) {
        await api(`/trades/${params.id}/checklist`, {
          method: "PUT",
          body: JSON.stringify({
            responses: selectedPlan.checklist_items.map((item) => ({
              checklist_item_id: item.id,
              passed: checklistResponses[item.id] ?? null,
              note: null,
            })),
          }),
        });
      }
      setContext(await api<PlaybookContext>(`/trades/${params.id}/playbooks`));
      setTrade(updated);
      setDirty(false);
      setSaved(true);
      window.setTimeout(() => setSaved(false), 2200);
      if (advance && updated.next_trade_id) {
        router.push(`/trades/${updated.next_trade_id}${navSuffix}`);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Trade journal could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  const selectedSequenceTrades = useMemo(() => {
    const byId = new Map((sequenceCandidates?.items ?? []).map((item) => [item.id, item]));
    return sequenceSelected
      .map((id) => byId.get(id))
      .filter((item): item is SequenceCandidate => Boolean(item))
      .sort((a, b) => a.entry_timestamp.localeCompare(b.entry_timestamp));
  }, [sequenceCandidates, sequenceSelected]);

  function toggleSequenceTrade(candidate: SequenceCandidate) {
    if (candidate.id === params.id) return;
    if (candidate.sequence_id && candidate.sequence_id !== sequence?.id) return;
    setSequenceDirty(true);
    setSequenceSelected((current) =>
      current.includes(candidate.id)
        ? current.filter((id) => id !== candidate.id)
        : [...current, candidate.id],
    );
  }

  async function saveSequence() {
    if (!trade || sequenceSelected.length < 2) return;
    setSequenceSaving(true);
    setError("");
    try {
      await persistSequence();
      setSaved(true);
      window.setTimeout(() => setSaved(false), 2200);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Trade sequence could not be saved.");
    } finally {
      setSequenceSaving(false);
    }
  }

  async function removeSequence() {
    if (!sequence) return;
    setSequenceSaving(true);
    setError("");
    try {
      await api(`/trade-sequences/${sequence.id}`, { method: "DELETE" });
      setSequence(null);
      setSequenceSelected([params.id]);
      setSequenceNotes({});
      setSequenceTitle("");
      setSequenceThesis("");
      setSequenceContext("");
      setSequenceLesson("");
      setSequenceDirty(false);
      setSequencePickerOpen(false);
      setSequenceCandidates(
        await api<SequenceCandidates>(`/trades/${params.id}/sequence-candidates?date_mode=${dateMode}`),
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Trade sequence could not be removed.");
    } finally {
      setSequenceSaving(false);
    }
  }

  async function uploadScreenshot(file: File | undefined) {
    if (!file) return;
    const body = new FormData();
    body.append("file", file);
    try {
      await api(`/attachments?trade_id=${params.id}`, { method: "POST", body });
      setScreenshots(
        await api<Screenshot[]>(`/trades/${params.id}/attachments`),
      );
      setSaved(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Screenshot upload failed.");
    }
  }

  async function confirmCapture(capture: CompanionCapture) {
    if (capture.matched_trade_id !== params.id) return;
    setCaptureActionId(capture.id);
    setError("");
    try {
      const updated = await api<CompanionCapture>(`/captures/${capture.id}/match/${params.id}`, { method: "POST" });
      setCompanionCaptures((current) =>
        current.map((item) => (item.id === capture.id ? updated : item)),
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Capture match could not be confirmed.");
    } finally {
      setCaptureActionId(null);
    }
  }

  async function dismissCapture(capture: CompanionCapture) {
    setCaptureActionId(capture.id);
    setError("");
    try {
      await api(`/captures/${capture.id}/unmatch`, { method: "POST" });
      setCompanionCaptures((current) => current.filter((item) => item.id !== capture.id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Possible match could not be dismissed.");
    } finally {
      setCaptureActionId(null);
    }
  }

  if (error && !trade) return <ErrorState message={error} />;
  if (!trade) return <Skeleton rows={6} />;
  const journal = trade.journal ?? {};
  const manualScreenshots = screenshots.filter((item) => !item.filename.startsWith("companion-"));
  const matchedCaptures = companionCaptures.filter((item) => item.match_status === "matched");
  return (
    <>
      <PageHeader
        eyebrow="Focused trade review"
        title={`${trade.symbol} · ${trade.side}`}
        description={`${dateTime(trade.entry_timestamp, { dateStyle: "full", timeStyle: "short" })} · ${trade.review_position.date_mode === "trading" ? "Trading day" : "Calendar day"} ${trade.review_position.date} · Trade ${trade.review_position.index} of ${trade.review_position.count}`}
        action={
          <div className="review-nav review-flow-nav">
            {trade.previous_trade_id ? (
              <Link className="button" href={`/trades/${trade.previous_trade_id}${navSuffix}`}>
                ‹ Previous
              </Link>
            ) : <span />}
            <span className="review-progress">{trade.review_position.index} / {trade.review_position.count}</span>
            {trade.next_trade_id ? (
              <Link className="button" href={`/trades/${trade.next_trade_id}${navSuffix}`}>
                Next ›
              </Link>
            ) : <span />}
          </div>
        }
      />
      {error && <ErrorState message={error} />}
      {!!trade.reconciliation_warnings.length && (
        <div className="notice warning">
          <strong>Reconciliation needs attention.</strong>
          {trade.reconciliation_warnings.map((warning) => <p key={warning}>{warning}</p>)}
        </div>
      )}
      {viewer && (
        <div className="screenshot-lightbox" role="dialog" aria-modal="true" aria-label="Screenshot preview" onMouseDown={(event) => { if (event.target === event.currentTarget) setViewer(null); }}>
          <div className="screenshot-lightbox-card">
            <div className="screenshot-lightbox-actions">
              {viewer.captureId && <Link className="button quiet compact" href={`/captures?selected=${viewer.captureId}`}>Open capture</Link>}
              <button className="button compact" type="button" onClick={() => setViewer(null)}>Close</button>
            </div>
            <AuthenticatedImage path={viewer.path} alt={viewer.alt} />
          </div>
        </div>
      )}
      <section className="review-layout">
        <div className="review-main">
          <article className="card trade-context-card">
            <div className="section-title">
              <div><p className="eyebrow">Trade context</p><h2>Charts, captures, and live reasoning</h2></div>
              <label className="button">
                Add screenshot
                <input
                  type="file"
                  accept="image/*"
                  hidden
                  onChange={(event) => void uploadScreenshot(event.target.files?.[0])}
                />
              </label>
            </div>

            {!manualScreenshots.length && !companionCaptures.length ? (
              <div className="screenshot-empty">
                <Icon name="journal" />
                <p>No visual context yet.</p>
                <small>Companion captures and screenshots you add later will appear together here.</small>
              </div>
            ) : (
              <div className="trade-context-feed">
                {companionCaptures.map((capture) => {
                  const possible = capture.match_status === "suggested";
                  const busy = captureActionId === capture.id;
                  return (
                    <article className={`trade-context-item companion ${possible ? "possible" : ""}`} key={capture.id}>
                      <div className="trade-context-item-head">
                        <div className="trade-context-source-row">
                          <span className={`context-source-badge ${possible ? "possible" : "companion"}`}>{possible ? "Possible match" : "Companion"}</span>
                          <span className="context-event">{(capture.phase || capture.event_type).replaceAll("_", " ")} · {timeOnly(capture.captured_at)}{capture.recorded_live === false ? " · added later" : ""}</span>
                        </div>
                        <Link className="button quiet compact" href={`/captures?selected=${capture.id}`}>Open capture</Link>
                      </div>
                      <div className="trade-context-item-body">
                        {capture.screenshot_url ? (
                          <button
                            className="trade-context-image"
                            type="button"
                            onClick={() => setViewer({
                              path: capture.screenshot_url as string,
                              alt: `${possible ? "Possible" : "Companion"} ${capture.phase || capture.event_type} moment`,
                              captureId: capture.id,
                            })}
                            aria-label="Enlarge capture"
                          >
                            <AuthenticatedImage path={capture.screenshot_url} alt={`${possible ? "Possible" : "Companion"} ${capture.phase || capture.event_type} moment`} />
                          </button>
                        ) : (
                          <div className="trade-context-image trade-context-text-only">Text-only Companion moment</div>
                        )}
                        <div className="trade-context-copy">
                          {possible && (
                            <div className="possible-match-panel">
                              <strong>Not matched yet</strong>
                              <p>JournalMe thinks this capture may belong to this trade. Use the chart and note to decide.</p>
                              <div>
                                <button className="button primary compact" type="button" disabled={busy} onClick={() => void confirmCapture(capture)}>
                                  {busy ? "Working..." : "Confirm match"}
                                </button>
                                <button className="button quiet compact" type="button" disabled={busy} onClick={() => void dismissCapture(capture)}>Not this trade</button>
                              </div>
                            </div>
                          )}
                          {capture.note && <div className="companion-quick-note"><span>What I was seeing</span><p>{capture.note}</p></div>}
                          {(capture.setup_tags.length > 0 || capture.execution_tags.length > 0 || capture.emotion_tags.length > 0) && (
                            <div className="companion-context-tags">
                              {[...capture.setup_tags, ...capture.execution_tags, ...capture.emotion_tags].map((tag) => <em key={`${capture.id}-${tag}`}>{tag}</em>)}
                            </div>
                          )}
                        </div>
                      </div>
                    </article>
                  );
                })}

                {manualScreenshots.map((screenshot) => (
                  <article className="trade-context-item manual" key={screenshot.id}>
                    <div className="trade-context-item-head">
                      <div className="trade-context-source-row">
                        <span className="context-source-badge manual">Manual</span>
                        <span className="context-event">Added to this trade</span>
                      </div>
                    </div>
                    <button
                      className="trade-context-manual-image"
                      type="button"
                      onClick={() => setViewer({ path: screenshot.content_url, alt: screenshot.caption || screenshot.filename })}
                      aria-label="Enlarge screenshot"
                    >
                      <AuthenticatedImage path={screenshot.content_url} alt={screenshot.caption || screenshot.filename} />
                    </button>
                    {screenshot.caption && <p className="trade-context-caption">{screenshot.caption}</p>}
                  </article>
                ))}
              </div>
            )}
          </article>
          {matchedCaptures.length > 0 && (
            <section className="card already-captured-card">
              <div className="section-title">
                <div><p className="eyebrow">JournalMe already captured</p><h2>Use this as context, not another form to repeat.</h2></div>
                <span>{matchedCaptures.length} companion capture{matchedCaptures.length === 1 ? "" : "s"}</span>
              </div>
              <div className="already-captured-list">
                {matchedCaptures.map((capture) => (
                  <div key={capture.id}>
                    <strong>{(capture.phase || capture.event_type).replaceAll("_", " ")} · {timeOnly(capture.captured_at)}{capture.recorded_live === false ? " · added later" : ""}</strong>
                    {capture.note && <p>{capture.note}</p>}
                    {[...capture.setup_tags, ...capture.execution_tags, ...capture.emotion_tags].length > 0 && (
                      <div className="companion-context-tags">
                        {[...capture.setup_tags, ...capture.execution_tags, ...capture.emotion_tags].map((tag) => <em key={`${capture.id}-known-${tag}`}>{tag}</em>)}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </section>
          )}
          <section className="card trade-sequence-card">
            <div className="section-title trade-sequence-heading">
              <div>
                <p className="eyebrow">Trade sequence · optional</p>
                <h2>{sequence?.title || (sequence ? "One idea, several executions" : "Tie related trades together")}</h2>
                <p className="review-guidance">Keep every broker trade separate. Put the shared goal here once, then add only what changed on each execution.</p>
              </div>
              {sequence && <Pnl value={sequence.summary.net_pnl}>{money(sequence.summary.net_pnl)}</Pnl>}
            </div>

            <div className="trade-sequence-strip" aria-label="Trades in this sequence">
              {selectedSequenceTrades.map((item, index) => (
                <Fragment key={item.id}>
                  {index > 0 && <span className="trade-sequence-plus" aria-hidden="true">＋</span>}
                  <article className={`trade-sequence-tile ${item.id === params.id ? "current" : ""}`}>
                    <div className="trade-sequence-tile-head">
                      <Link href={`/trades/${item.id}${navSuffix}`}>
                        <strong>{timeOnly(item.entry_timestamp)} · {item.side}</strong>
                        <span>{item.symbol}</span>
                      </Link>
                      <Pnl value={item.net_pnl}>{money(item.net_pnl)}</Pnl>
                    </div>
                    <input
                      aria-label={`Small note for ${item.symbol} at ${timeOnly(item.entry_timestamp)}`}
                      value={sequenceNotes[item.id] ?? ""}
                      onChange={(event) => { setSequenceNotes((current) => ({ ...current, [item.id]: event.target.value })); setSequenceDirty(true); }}
                      placeholder={item.id === params.id ? "What changed on this execution?" : "Tiny update · optional"}
                    />
                    {item.id !== params.id && (
                      <button className="sequence-remove" type="button" onClick={() => toggleSequenceTrade(item)}>Remove</button>
                    )}
                  </article>
                </Fragment>
              ))}
              <button className="trade-sequence-add" type="button" onClick={() => setSequencePickerOpen((open) => !open)}>
                <span>＋</span>
                <strong>Add related trade</strong>
                <small>Same {dateMode === "trading" ? "trading" : "calendar"} day</small>
              </button>
            </div>

            {sequencePickerOpen && sequenceCandidates && (
              <div className="trade-sequence-picker">
                <div className="trade-sequence-picker-head">
                  <div><strong>Trades from {sequenceCandidates.date}</strong><small>Select executions that belonged to the same overall idea.</small></div>
                  <button className="button quiet compact" type="button" onClick={() => setSequencePickerOpen(false)}>Done</button>
                </div>
                <div className="trade-sequence-candidates">
                  {sequenceCandidates.items.map((candidate) => {
                    const selected = sequenceSelected.includes(candidate.id);
                    const belongsElsewhere = Boolean(candidate.sequence_id && candidate.sequence_id !== sequence?.id);
                    return (
                      <button
                        type="button"
                        key={candidate.id}
                        className={selected ? "selected" : ""}
                        disabled={candidate.id === params.id || belongsElsewhere}
                        onClick={() => toggleSequenceTrade(candidate)}
                      >
                        <span>{selected ? "✓" : "+"}</span>
                        <strong>{timeOnly(candidate.entry_timestamp)} · {candidate.side}</strong>
                        <small>{candidate.symbol} · {money(candidate.net_pnl)}</small>
                        {belongsElsewhere && <em>Already in another sequence</em>}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            {(sequence || sequenceSelected.length > 1) && (
              <div className="trade-sequence-shared">
                <div className="form-grid">
                  <div className="field span-2">
                    <label htmlFor="sequence-title">Sequence title <span className="muted">optional</span></label>
                    <input id="sequence-title" value={sequenceTitle} onChange={(event) => { setSequenceTitle(event.target.value); setSequenceDirty(true); }} placeholder="NY bearish continuation" />
                  </div>
                  <div className="field span-2">
                    <label htmlFor="sequence-goal">Overall goal / context</label>
                    <textarea id="sequence-goal" value={sequenceContext} onChange={(event) => { setSequenceContext(event.target.value); setSequenceDirty(true); }} placeholder="What were you trying to accomplish across all of these trades?" />
                  </div>
                  <div className="field span-2">
                    <label htmlFor="sequence-thesis">Overall read / thesis</label>
                    <textarea id="sequence-thesis" value={sequenceThesis} onChange={(event) => { setSequenceThesis(event.target.value); setSequenceDirty(true); }} placeholder="The shared market idea only needs to be written once." />
                  </div>
                  <div className="field span-2">
                    <label htmlFor="sequence-lesson">Sequence lesson <span className="muted">optional</span></label>
                    <textarea id="sequence-lesson" value={sequenceLesson} onChange={(event) => { setSequenceLesson(event.target.value); setSequenceDirty(true); }} placeholder="What did the whole run of executions teach you?" />
                  </div>
                </div>
                <div className="trade-sequence-actions">
                  <button className="button primary" type="button" disabled={sequenceSaving || sequenceSelected.length < 2} onClick={() => void saveSequence()}>
                    {sequenceSaving ? "Saving..." : sequence ? "Save sequence" : `Tie ${sequenceSelected.length} trades`}
                  </button>
                  {sequence && <button className="button quiet" type="button" disabled={sequenceSaving} onClick={() => void removeSequence()}>Untie sequence</button>}
                  <small>{sequenceSelected.length} separate broker trade{sequenceSelected.length === 1 ? "" : "s"} · accounting stays unchanged · Save review also saves sequence edits</small>
                </div>
              </div>
            )}
          </section>

          <form
            key={trade.id}
            id="trade-review-form"
            className="card review-form"
            onSubmit={submit}
            onChange={() => {
              setDirty(true);
              setSaved(false);
            }}
          >
            <div className="section-title">
              <div><p className="eyebrow">Your perspective</p><h2>Quick recap</h2></div>
              <span className={dirty || sequenceDirty ? "unsaved" : saved ? "positive" : "muted"}>
                {dirty || sequenceDirty ? "Unsaved changes" : saved ? "Saved" : "Up to date"}
              </span>
            </div>
            <p className="review-guidance">{sequence ? "The shared trade idea is saved above. Use this recap only for what was unique about this execution." : "Add only the part JournalMe could not observe from fills, charts, or Companion. Open Advanced review when the extra detail is useful."}</p>
            <div className="form-grid quick-trade-review">
              <div className="field span-2">
                <label htmlFor="thesis">{sequence ? "This execution only" : "Your read"}</label>
                <textarea id="thesis" name="thesis" defaultValue={String(journal.thesis ?? "")} placeholder={sequence ? "What changed on this specific entry, exit, or re-entry? Optional if the sequence note already covers it." : "What was the idea or decision that mattered?"} />
              </div>
              <div className="field">
                <label htmlFor="went-well">What would you repeat?</label>
                <textarea id="went-well" name="what_went_well" defaultValue={String(journal.what_went_well ?? "")} placeholder="One thing worth keeping." />
              </div>
              <div className="field">
                <label htmlFor="went-wrong">What would you change?</label>
                <textarea id="went-wrong" name="what_went_wrong" defaultValue={String(journal.what_went_wrong ?? "")} placeholder="One adjustment for next time." />
              </div>
              <div className="field span-2">
                <label htmlFor="lesson">Lesson to carry forward</label>
                <textarea id="lesson" name="lesson_learned" defaultValue={String(journal.lesson_learned ?? "")} placeholder="Optional if the lesson is already clear above." />
              </div>
              <div className="field">
                <label htmlFor="grade">Trade grade</label>
                <select id="grade" name="trade_grade" defaultValue={String(journal.trade_grade ?? "")}>
                  <option value="">Not graded</option>
                  {["A+", "A", "B", "C", "D", "F"].map((grade) => <option key={grade}>{grade}</option>)}
                </select>
              </div>
              <div className="field">
                <label htmlFor="followed-plan">Followed plan</label>
                <select id="followed-plan" name="followed_plan" defaultValue={journal.followed_plan === null || journal.followed_plan === undefined ? "" : String(journal.followed_plan)}>
                  <option value="">Not answered</option><option value="true">Yes</option><option value="false">No</option>
                </select>
              </div>
            </div>

            <details className="advanced-review">
              <summary><span><strong>Advanced review</strong><small>Execution reasoning, emotions, scores, playbook, checklist, and tags</small></span><span aria-hidden="true">＋</span></summary>
              <div className="advanced-review-body">
                <div className="form-grid">
                  <div className="field">
                    <label htmlFor="best-decision">Best decision</label>
                    <textarea id="best-decision" name="best_decision" defaultValue={String(journal.best_decision ?? "")} />
                  </div>
                  <div className="field">
                    <label htmlFor="worst-decision">Worst decision</label>
                    <textarea id="worst-decision" name="worst_decision" defaultValue={String(journal.worst_decision ?? "")} />
                  </div>
                  <div className="field">
                    <label htmlFor="entry-reason">Why did you enter?</label>
                    <textarea id="entry-reason" name="entry_reason" defaultValue={String(journal.entry_reason ?? "")} />
                  </div>
                  <div className="field">
                    <label htmlFor="exit-reason">Why did you exit?</label>
                    <textarea id="exit-reason" name="exit_reason" defaultValue={String(journal.exit_reason ?? "")} />
                  </div>
                  <div className="field">
                    <label htmlFor="pre-emotion">Emotion before</label>
                    <input id="pre-emotion" name="pre_trade_emotion" defaultValue={String(journal.pre_trade_emotion ?? "")} />
                  </div>
                  <div className="field">
                    <label htmlFor="post-emotion">Emotion after</label>
                    <input id="post-emotion" name="post_trade_emotion" defaultValue={String(journal.post_trade_emotion ?? "")} />
                  </div>
                  <div className="field">
                    <label htmlFor="confidence-score">Confidence</label>
                    <select id="confidence-score" name="confidence_score" defaultValue={String(journal.confidence_score ?? "")}><option value="">Not scored</option>{[1, 2, 3, 4, 5].map((score) => <option key={score}>{score}</option>)}</select>
                  </div>
                  <div className="field">
                    <label htmlFor="patience-score">Patience</label>
                    <select id="patience-score" name="patience_score" defaultValue={String(journal.patience_score ?? "")}><option value="">Not scored</option>{[1, 2, 3, 4, 5].map((score) => <option key={score}>{score}</option>)}</select>
                  </div>
                  <div className="field">
                    <label htmlFor="discipline-score">Discipline</label>
                    <select id="discipline-score" name="discipline_score" defaultValue={String(journal.discipline_score ?? "")}><option value="">Not scored</option>{[1, 2, 3, 4, 5].map((score) => <option key={score}>{score}</option>)}</select>
                  </div>
                  <div className="field">
                    <label htmlFor="session-name">Trading session</label>
                    <input id="session-name" name="session_name" defaultValue={String(journal.session_name ?? "")} placeholder="New York open" />
                  </div>
                  <div className="field span-2">
                    <label htmlFor="market-condition">Market condition</label>
                    <input id="market-condition" name="market_condition" defaultValue={String(journal.market_condition ?? "")} placeholder="Trending, balanced, volatile…" />
                  </div>
                  <div className="field span-2">
                    <label htmlFor="custom-notes">Additional notes</label>
                    <textarea id="custom-notes" name="custom_notes" defaultValue={String(journal.custom_notes ?? "")} />
                  </div>
                </div>
                <div className="playbook-assignment">
                  <div className="section-title"><div><p className="eyebrow">Strategy context</p><h2>Primary playbook</h2></div>{context && <strong className={`status-text ${context.review.status}`}>{context.review.status}</strong>}</div>
                  <div className="field"><label htmlFor="primary-playbook">Playbook</label><select id="primary-playbook" value={primaryPlaybook} onChange={(event) => { setPrimaryPlaybook(event.target.value); setDirty(true); }}><option value="">Not assigned</option>{playbooks.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></div>
                  {playbooks.find((item) => item.id === primaryPlaybook)?.checklist_items.map((item) => <label className="check-response" key={item.id}><input type="checkbox" checked={checklistResponses[item.id] === true} onChange={(event) => { setChecklistResponses((current) => ({ ...current, [item.id]: event.target.checked })); setDirty(true); }} /><span><strong>{item.text}</strong><small>{item.category} · {item.required ? "Must pass" : "Optional"}</small></span></label>)}
                  {context?.review.missing.length ? <p className="completion-note">For a full review: {context.review.missing.join(" · ")}</p> : <p className="completion-note complete">Full review requirements complete.</p>}
                </div>
                <div className="tag-editor">
                  {Object.entries(groupedTags).map(([category, values]) => (
                    <fieldset key={category}>
                      <legend>{category}</legend>
                      <div>
                        {values.map((tag) => (
                          <label key={tag.id} className={selectedTags.includes(tag.id) ? "selected" : ""}>
                            <input
                              type="checkbox"
                              checked={selectedTags.includes(tag.id)}
                              onChange={() =>
                                setSelectedTags((current) =>
                                  current.includes(tag.id)
                                    ? current.filter((id) => id !== tag.id)
                                    : [...current, tag.id],
                                )
                              }
                            />
                            {tag.name}
                          </label>
                        ))}
                      </div>
                    </fieldset>
                  ))}
                </div>
              </div>
            </details>
            <div className="form-actions review-flow-dock">
              <div className="review-flow-dock-nav">
                {trade.previous_trade_id ? <Link className="button quiet" href={`/trades/${trade.previous_trade_id}${navSuffix}`}>‹ Previous</Link> : <span />}
                <span className="review-progress">Trade {trade.review_position.index} of {trade.review_position.count}</span>
              </div>
              <div className="review-flow-dock-actions">
                <button className="button" disabled={saving}>
                  {saving ? "Saving..." : "Save review"}
                </button>
                {trade.next_trade_id && (
                  <button className="button primary" data-advance="true" disabled={saving}>
                    {saving ? "Saving..." : "Save & next ›"}
                  </button>
                )}
                {!trade.next_trade_id && <span className="completion-note complete">Last trade in this {dateMode === "trading" ? "trading" : "calendar"} day.</span>}
              </div>
            </div>
          </form>
        </div>
        <aside className="review-aside">
          <article className="card execution-summary">
            <p className="eyebrow">Execution facts</p>
            <dl>
              <div><dt>Net P&L</dt><dd><Pnl value={trade.net_pnl}>{money(trade.net_pnl)}</Pnl></dd></div>
              <div><dt>Gross P&L</dt><dd>{money(trade.gross_pnl)}</dd></div>
              <div><dt>Fees</dt><dd>{money(trade.fees)}</dd></div>
              <div><dt>Quantity</dt><dd>{quantity(trade.quantity, true)}</dd></div>
              <div><dt>Entry</dt><dd>{price(trade.entry_price)}</dd></div>
              <div><dt>Exit</dt><dd>{price(trade.exit_price)}</dd></div>
              <div><dt>Duration</dt><dd>{duration(trade.duration_seconds)}</dd></div>
              <div><dt>Source</dt><dd>{trade.source_quality.replaceAll("_", " ")}</dd></div>
              <div><dt>Review</dt><dd className={`status-text ${context?.review.status ?? "unreviewed"}`}>{context?.review.status ?? "unreviewed"}</dd></div>
            </dl>
            <Link className="button full" href={`/timeline/${trade.review_position.date}${dateMode === "calendar" ? "?mode=calendar" : ""}`}>Open {dateMode === "trading" ? "trading" : "calendar"} day</Link>
          </article>
          <article className="card fills-card">
            <p className="eyebrow">Linked fills</p>
            {executions?.fills.map((fill) => (
              <div key={fill.id}>
                <span className={`side-token ${fill.action}`}>{fill.action}</span>
                <strong>{quantity(fill.quantity)} @ {price(fill.price)}</strong>
                <small>{timeOnly(fill.timestamp, { second: "2-digit" })} · {money(fill.commission)} fee</small>
              </div>
            ))}
            {!executions?.fills.length && <p className="muted">Execution-level fills unavailable.</p>}
          </article>
          <article className="card fills-card">
            <p className="eyebrow">Linked orders</p>
            {executions?.orders.map((order) => <div key={order.id}><span className="side-token">{order.status}</span><strong>{order.type ?? "Order"}</strong><small>{order.limit_price ? `Limit ${price(order.limit_price)}` : ""}{order.stop_price ? ` · Stop ${price(order.stop_price)}` : ""}</small></div>)}
            {!executions?.orders.length && <p className="muted">Order-level details unavailable.</p>}
          </article>
        </aside>
      </section>
    </>
  );
}
