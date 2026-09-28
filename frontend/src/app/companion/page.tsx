"use client";

import { ChangeEvent, useEffect, useMemo, useState } from "react";

import { useAccount } from "@/components/account-provider";
import { AuthenticatedImage } from "@/components/authenticated-assets";
import { ErrorState, PageHeader } from "@/components/ui";
import { api, dateTime, money } from "@/lib/api";
import type {
  CompanionMomentCreateResponse,
  CompanionMomentPhase,
  TradingEpisode,
} from "@/lib/types";

const PHASES: { value: CompanionMomentPhase; label: string }[] = [
  { value: "pre_entry", label: "Pre-entry" },
  { value: "confirmation", label: "Confirmation" },
  { value: "entry", label: "Entry" },
  { value: "management", label: "Management" },
  { value: "exit", label: "Exit" },
  { value: "wait", label: "Wait" },
  { value: "post_trade", label: "Post-trade" },
];

const SETUP_TAGS = [
  "Liquidity Sweep", "Prior Day High/Low", "Session High/Low", "Asia High/Low",
  "London High/Low", "Equal Highs/Lows", "FVG", "IFVG", "1H FVG", "4H FVG",
  "HTF PD Array", "Displacement", "Market Structure Shift", "Order Block", "Breaker",
  "Opening Range", "VWAP Reclaim", "VWAP Rejection", "RSI Divergence", "Trend Continuation",
];

const EXECUTION_TAGS = [
  "Patient Entry", "Waited for Sweep", "Waited for Displacement", "FVG Entry",
  "IFVG Confirmation", "Structure Confirmation", "Good Confirmation", "Clean Risk",
  "Entered Early", "Entered Late", "Chased", "No Confirmation", "Missed Entry",
  "Stop Too Tight", "Moved Stop", "Oversized", "Cut Winner Early", "Took Profit Early",
  "Added to Loser", "FOMO", "Revenge Trade", "Overtrading", "Rule Break",
];

const EMOTION_TAGS = [
  "Neutral", "Calm", "Focused", "Locked In", "Confident", "Patient", "Hesitant",
  "Distracted", "Frustrated", "Anxious", "Fearful", "Greedy", "Overconfident",
  "Tilted", "Rushed", "Bored", "Tired",
];

function phaseLabel(value: CompanionMomentPhase | null): string {
  if (!value) return "Moment";
  return PHASES.find((item) => item.value === value)?.label ?? value.replaceAll("_", " ");
}

function shortTime(value: string): string {
  return new Intl.DateTimeFormat("en-US", {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  }).format(new Date(value));
}

function ToggleTags({
  title,
  values,
  selected,
  onToggle,
}: {
  title: string;
  values: string[];
  selected: string[];
  onToggle: (value: string) => void;
}) {
  return (
    <div className="companion-tag-group">
      <span>{title}</span>
      <div className="companion-chips">
        {values.map((value) => (
          <button
            key={value}
            type="button"
            className={selected.includes(value) ? "selected" : ""}
            onClick={() => onToggle(value)}
          >
            {value}
          </button>
        ))}
      </div>
    </div>
  );
}

function EpisodeTimeline({ episode }: { episode: TradingEpisode }) {
  const moments = episode.moments ?? [];
  if (!moments.length) {
    return <p className="muted small">Your first saved moment will appear here.</p>;
  }
  return (
    <div className="companion-timeline">
      {moments.map((moment) => (
        <article key={moment.id} className="companion-moment">
          <div className="companion-moment-head">
            <strong>{shortTime(moment.captured_at)}</strong>
            <span>{phaseLabel(moment.phase)}</span>
            {!moment.recorded_live && <em>added later</em>}
          </div>
          {moment.has_screenshot && moment.screenshot_url && (
            <div className="companion-moment-image">
              <AuthenticatedImage
                path={moment.screenshot_url}
                alt={`${moment.symbol ?? episode.symbol ?? "Trading"} chart at ${shortTime(moment.captured_at)}`}
              />
            </div>
          )}
          {moment.note && <p>{moment.note}</p>}
          {[...moment.setup_tags, ...moment.execution_tags, ...moment.emotion_tags].length > 0 && (
            <div className="companion-moment-tags">
              {[...moment.setup_tags, ...moment.execution_tags, ...moment.emotion_tags].map((tag) => (
                <span key={tag}>{tag}</span>
              ))}
            </div>
          )}
        </article>
      ))}
    </div>
  );
}

export default function CompanionPage() {
  const { account } = useAccount();
  const [active, setActive] = useState<TradingEpisode | null>(null);
  const [recent, setRecent] = useState<TradingEpisode[]>([]);
  const [selectedEpisode, setSelectedEpisode] = useState<TradingEpisode | null>(null);
  const [note, setNote] = useState("");
  const [symbol, setSymbol] = useState("");
  const [side, setSide] = useState<"long" | "short" | "">("");
  const [phase, setPhase] = useState<CompanionMomentPhase | null>(null);
  const [image, setImage] = useState<File | null>(null);
  const [setupTags, setSetupTags] = useState<string[]>([]);
  const [executionTags, setExecutionTags] = useState<string[]>([]);
  const [emotionTags, setEmotionTags] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");

  const previewUrl = useMemo(() => image ? URL.createObjectURL(image) : null, [image]);

  useEffect(() => () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
  }, [previewUrl]);

  async function refresh() {
    if (!account) {
      setActive(null);
      setRecent([]);
      setLoading(false);
      return;
    }
    setError("");
    try {
      const [activeEpisode, recentEpisodes] = await Promise.all([
        api<TradingEpisode | null>(`/captures/episodes/active?account_id=${account.id}`, { cache: "no-cache" }),
        api<TradingEpisode[]>(`/captures/episodes?account_id=${account.id}&limit=8`, { cache: "no-cache" }),
      ]);
      setActive(activeEpisode);
      setRecent(recentEpisodes);
      if (activeEpisode?.symbol) setSymbol((current) => current || activeEpisode.symbol || "");
      if (activeEpisode?.side) setSide((current) => current || activeEpisode.side || "");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Companion could not be loaded.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setLoading(true);
    void refresh();
    // refresh is intentionally tied to the selected account.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [account?.id]);

  function toggle(values: string[], setter: (next: string[]) => void, value: string) {
    setter(values.includes(value) ? values.filter((item) => item !== value) : [...values, value]);
  }

  function chooseImage(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    setImage(file);
    setStatus(file ? "Screenshot ready to attach." : "");
  }

  async function saveMoment() {
    if (!account) return;
    if (!note.trim() && !image && !setupTags.length && !executionTags.length && !emotionTags.length) {
      setError("Add a thought, screenshot, or optional context before saving.");
      return;
    }
    setSaving(true);
    setError("");
    setStatus("");
    try {
      const capturedAt = image?.lastModified ? new Date(image.lastModified) : new Date();
      const recordedLive = Math.abs(Date.now() - capturedAt.getTime()) <= 15 * 60 * 1000;
      const metadata = {
        episode_id: active?.id ?? null,
        account_id: account.id,
        captured_at: capturedAt.toISOString(),
        phase,
        symbol: symbol.trim().toUpperCase() || active?.symbol || null,
        side: side || active?.side || null,
        note: note.trim() || null,
        setup_tags: setupTags,
        execution_tags: executionTags,
        emotion_tags: emotionTags,
        platform: "JournalMe PWA",
        source: "journalme_mobile_companion",
        recorded_live: recordedLive,
      };
      const form = new FormData();
      form.append("metadata", JSON.stringify(metadata));
      if (image) form.append("screenshot", image, image.name || `journalme-mobile-${Date.now()}.png`);
      const saved = await api<CompanionMomentCreateResponse>("/captures/moments", {
        method: "POST",
        body: form,
      });
      setActive(saved.episode.status === "active" ? saved.episode : null);
      setStatus(saved.episode.status === "active" ? "Moment saved to the active episode." : "Moment saved. Episode complete.");
      setNote("");
      setImage(null);
      setPhase(null);
      setSetupTags([]);
      setExecutionTags([]);
      setEmotionTags([]);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Moment could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  async function endEpisode() {
    if (!active) return;
    setError("");
    try {
      await api(`/captures/episodes/${active.id}/complete`, { method: "POST" });
      setActive(null);
      setStatus("Episode ended. Your next saved moment can start a new one.");
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Episode could not be ended.");
    }
  }

  async function viewEpisode(id: string) {
    setError("");
    try {
      setSelectedEpisode(await api<TradingEpisode>(`/captures/episodes/${id}`, { cache: "no-cache" }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Episode could not be loaded.");
    }
  }

  return (
    <div className="companion-page">
      <PageHeader
        eyebrow="Live capture"
        title="Companion mode"
        description="Capture what you see and think in the moment. One update is enough; add more only when they help."
      />

      {error && <ErrorState message={error} />}
      {loading && <div className="card companion-loading">Loading Companion…</div>}

      {!loading && (
        <>
          <section className="card companion-active-card">
            <div className="companion-active-head">
              <div>
                <p className="eyebrow">{active ? "Active episode" : "Ready when you are"}</p>
                <h2>{active ? `${active.symbol ?? (symbol || "Trading observation")}${active.side ? ` · ${active.side.toUpperCase()}` : ""}` : "Start with one moment"}</h2>
                <p className="muted">
                  {active
                    ? `Started ${dateTime(active.started_at, { hour: "numeric", minute: "2-digit" })} · ${active.moment_count} ${active.moment_count === 1 ? "moment" : "moments"}`
                    : "Your first saved thought, screenshot, or tag automatically starts an episode."}
                </p>
              </div>
              {active && <button className="button quiet" type="button" onClick={() => void endEpisode()}>End episode</button>}
            </div>
            {active && <EpisodeTimeline episode={active} />}
          </section>

          <section className="card companion-capture-card">
            <div className="companion-capture-head">
              <div>
                <p className="eyebrow">Add moment</p>
                <h2>What changed?</h2>
              </div>
              <span>{account?.name ?? "No account"}</span>
            </div>

            <label className="companion-upload">
              <input type="file" accept="image/png,image/jpeg,image/webp,image/*" onChange={chooseImage} />
              <strong>{image ? "Change screenshot" : "Add screenshot"}</strong>
              <span>{image ? image.name : "Choose a screenshot from Photos or Files. Optional."}</span>
            </label>
            {previewUrl && (
              // The preview is a local object URL from the user-selected image.
              // eslint-disable-next-line @next/next/no-img-element
              <img className="companion-preview" src={previewUrl} alt="Selected chart screenshot" />
            )}

            <label className="companion-note-field">
              <span>Thought</span>
              <textarea
                value={note}
                onChange={(event) => setNote(event.target.value)}
                placeholder="What are you seeing, waiting for, or changing your mind about?"
                rows={4}
                maxLength={1000}
              />
            </label>

            <div className="companion-phase-row" aria-label="Optional moment phase">
              {PHASES.map((item) => (
                <button
                  key={item.value}
                  type="button"
                  className={phase === item.value ? "selected" : ""}
                  onClick={() => setPhase((current) => current === item.value ? null : item.value)}
                >
                  {item.label}
                </button>
              ))}
            </div>

            <div className="companion-symbol-row">
              <label>
                <span>Symbol</span>
                <input value={symbol} onChange={(event) => setSymbol(event.target.value.toUpperCase())} placeholder="MNQ" maxLength={24} />
              </label>
              <label>
                <span>Side</span>
                <select value={side} onChange={(event) => setSide(event.target.value as "long" | "short" | "")}>
                  <option value="">Not set</option>
                  <option value="long">Long</option>
                  <option value="short">Short</option>
                </select>
              </label>
            </div>

            <details className="companion-details">
              <summary>Add context <span>optional</span></summary>
              <ToggleTags title="Setup / context" values={SETUP_TAGS} selected={setupTags} onToggle={(value) => toggle(setupTags, setSetupTags, value)} />
              <ToggleTags title="Execution" values={EXECUTION_TAGS} selected={executionTags} onToggle={(value) => toggle(executionTags, setExecutionTags, value)} />
              <ToggleTags title="State" values={EMOTION_TAGS} selected={emotionTags} onToggle={(value) => toggle(emotionTags, setEmotionTags, value)} />
            </details>

            {status && <div className="notice success companion-status">{status}</div>}
            <button className="button primary companion-save" type="button" disabled={saving} onClick={() => void saveMoment()}>
              {saving ? "Saving…" : "Save moment"}
            </button>
          </section>

          <section className="card companion-recent-card">
            <div className="companion-section-head">
              <div>
                <p className="eyebrow">Recent episodes</p>
                <h2>Ideas, trades, and waits</h2>
              </div>
              <button className="button quiet" type="button" onClick={() => void refresh()}>Refresh</button>
            </div>
            {!recent.length && <p className="muted">No episode-based Companion activity yet. Existing legacy captures are still available on the Captures page.</p>}
            <div className="companion-episode-list">
              {recent.map((episode) => (
                <button key={episode.id} type="button" onClick={() => void viewEpisode(episode.id)}>
                  <span className="companion-episode-title">
                    <strong>{episode.symbol ?? "Observation"}</strong>
                    <em>{episode.status}</em>
                  </span>
                  <span>{episode.moment_count} {episode.moment_count === 1 ? "moment" : "moments"} · {episode.screenshot_count} {episode.screenshot_count === 1 ? "screenshot" : "screenshots"}</span>
                  <span>{dateTime(episode.started_at, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</span>
                  {episode.matched_trade && (
                    <span className={Number(episode.matched_trade.net_pnl) >= 0 ? "positive" : "negative"}>
                      Matched trade · {money(episode.matched_trade.net_pnl)}
                    </span>
                  )}
                  {episode.last_note && <small>{episode.last_note}</small>}
                </button>
              ))}
            </div>
          </section>

          {selectedEpisode && (
            <section className="card companion-history-card">
              <div className="companion-section-head">
                <div>
                  <p className="eyebrow">Episode timeline</p>
                  <h2>{selectedEpisode.symbol ?? "Trading observation"}</h2>
                </div>
                <button className="button quiet" type="button" onClick={() => setSelectedEpisode(null)}>Close</button>
              </div>
              <EpisodeTimeline episode={selectedEpisode} />
            </section>
          )}
        </>
      )}
    </div>
  );
}
