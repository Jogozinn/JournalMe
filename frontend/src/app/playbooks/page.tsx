"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useMemo, useState } from "react";

import { EmptyState, ErrorState, PageHeader, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import type { Playbook } from "@/lib/types";

type ChecklistSeed = {
  text: string;
  category: "entry" | "confirmation" | "risk" | "management";
  required: boolean;
  sort_order: number;
};

type PlaybookPreset = {
  key: string;
  name: string;
  short: string;
  tags: string[];
  body: {
    name: string;
    description: string;
    active: true;
    market_scope: string;
    direction_scope: "long" | "short" | "both";
    preferred_session: string;
    minimum_confluences: number;
    ideal_entry_criteria: string;
    confirmation_criteria: string;
    invalidation_criteria: string;
    stop_logic: string;
    target_logic: string;
    management_rules: string;
    prohibited_conditions: string;
    default_grade_expectations: string;
    checklist_items: ChecklistSeed[];
  };
};

const PLAYBOOK_PRESETS: PlaybookPreset[] = [
  {
    key: "waverr-narrative",
    name: "WaveRR Narrative Setup",
    short: "HTF location, liquidity, delivery, structural entry, and a defined draw on liquidity.",
    tags: ["HTF narrative", "Liquidity", "FVG / IFVG"],
    body: {
      name: "WaveRR Narrative Setup",
      description: "A broad narrative setup built around higher-timeframe location, liquidity behavior, tactical delivery, and structural execution.",
      active: true,
      market_scope: "Index futures",
      direction_scope: "both",
      preferred_session: "Any session",
      minimum_confluences: 3,
      ideal_entry_criteria: "Start with the higher-timeframe draw and location. Use 15m and 5m delivery to define the tactical path. Enter only when price interacts with meaningful liquidity or a PD array and the lower timeframe gives a clean structural reason to participate.",
      confirmation_criteria: "Relevant liquidity is taken or a meaningful PD array is engaged. Displacement confirms intent. FVG or IFVG behavior supports the direction. Lower-timeframe structure agrees with the trade role.",
      invalidation_criteria: "Price accepts beyond the structural invalidation, reclaims the opposing displacement, or the original draw on liquidity is no longer valid.",
      stop_logic: "Use a structural stop beyond the invalidation point with enough room for normal noise. Size from stop distance rather than forcing a fixed contract count.",
      target_logic: "Use the nearest meaningful liquidity or PD-array objective first. Local liquidity can finish a quick trade. Broader higher-timeframe draws are reserved for setups with enough context to support extension.",
      management_rules: "Treat sessions as context, not a direction filter. Manage according to the trade horizon. Preserve room for structure and reduce or exit when tactical delivery materially fails.",
      prohibited_conditions: "Do not enter because of RSI alone. Do not chase displacement. Do not force a trade because of the session name. Do not add risk after structural invalidation.",
      default_grade_expectations: "A-grade execution has a clear narrative, a defined liquidity objective, structural confirmation, planned risk, and no hindsight edits to the setup definition.",
      checklist_items: [
        { text: "Higher-timeframe location and draw are identified", category: "entry", required: true, sort_order: 0 },
        { text: "Relevant liquidity event or PD array is present", category: "confirmation", required: true, sort_order: 1 },
        { text: "15m and 5m delivery support the trade role", category: "confirmation", required: true, sort_order: 2 },
        { text: "FVG, IFVG, displacement, or structure confirms execution", category: "confirmation", required: true, sort_order: 3 },
        { text: "Structural stop and dollar risk are defined", category: "risk", required: true, sort_order: 4 },
        { text: "Target and trade horizon are defined before entry", category: "management", required: true, sort_order: 5 },
      ],
    },
  },
  {
    key: "liquidity-ifvg",
    name: "Liquidity Sweep + IFVG",
    short: "Sweep a meaningful high or low, wait for displacement, then use inversion for execution.",
    tags: ["Sweep", "Displacement", "IFVG"],
    body: {
      name: "Liquidity Sweep + IFVG",
      description: "A reversal or rotation setup after meaningful liquidity is swept and displacement creates an inversion entry.",
      active: true,
      market_scope: "Index futures",
      direction_scope: "both",
      preferred_session: "Any session",
      minimum_confluences: 3,
      ideal_entry_criteria: "Price sweeps a meaningful prior high, prior low, session extreme, or relative equal liquidity while trading at a location that can support a reaction. Wait for displacement away from the sweep and use a clean FVG inversion or equivalent structural retrace for entry.",
      confirmation_criteria: "The sweep is clear, displacement leaves the raid with intent, and the inversion holds on the execution timeframe. The next liquidity objective is visible before entry.",
      invalidation_criteria: "Price accepts back through the sweep extreme or the inversion fails and opposing structure takes control.",
      stop_logic: "Place the stop beyond the structural sweep or the level that invalidates the displacement thesis. Avoid stops inside normal retracement noise.",
      target_logic: "Target opposing intraday liquidity first. Extend only when the higher-timeframe narrative supports a larger rotation.",
      management_rules: "Do not front-run the sweep. Do not treat the first touch as confirmation. If displacement fails to hold, reduce or exit rather than defending the original idea.",
      prohibited_conditions: "No entry before liquidity is taken. No chase after the inversion has already expanded. No reversal solely because price touched an FVG.",
      default_grade_expectations: "A-grade execution waits for the raid, confirms displacement, enters at a planned inversion, and targets a known liquidity objective.",
      checklist_items: [
        { text: "Meaningful liquidity was swept", category: "entry", required: true, sort_order: 0 },
        { text: "Displacement confirmed a reaction away from the sweep", category: "confirmation", required: true, sort_order: 1 },
        { text: "FVG or IFVG inversion gave a defined entry", category: "confirmation", required: true, sort_order: 2 },
        { text: "Stop sits beyond structural invalidation", category: "risk", required: true, sort_order: 3 },
        { text: "Opposing liquidity target is identified", category: "management", required: true, sort_order: 4 },
      ],
    },
  },
  {
    key: "fvg-ifvg-continuation",
    name: "FVG / IFVG Continuation",
    short: "Use a directional narrative, displacement, and a retrace into imbalance for continuation.",
    tags: ["FVG", "IFVG", "Continuation"],
    body: {
      name: "FVG / IFVG Continuation",
      description: "A continuation setup that uses the broader directional narrative and a retrace into a valid imbalance after displacement.",
      active: true,
      market_scope: "Index futures",
      direction_scope: "both",
      preferred_session: "Any session",
      minimum_confluences: 3,
      ideal_entry_criteria: "The broader narrative already has a valid directional draw. Price displaces in that direction, then retraces into a clean FVG or IFVG at a location that preserves the continuation thesis.",
      confirmation_criteria: "Displacement is obvious, the imbalance remains relevant, and the retrace shows acceptance in the intended direction rather than a full structural reversal.",
      invalidation_criteria: "The imbalance fails, opposing structure takes control, or price invalidates the swing that supports continuation.",
      stop_logic: "Use the structural swing or the far side of the setup location when it represents real invalidation. Avoid arbitrary fixed-point stops.",
      target_logic: "Target the next external or internal liquidity objective that matches the planned horizon.",
      management_rules: "Let the trade work if structure remains valid. Do not convert a continuation trade into a hope trade after the delivery shifts against it.",
      prohibited_conditions: "No continuation entry without displacement. No FVG touch trade with no narrative. No chasing after price has already delivered to the nearest target.",
      default_grade_expectations: "A-grade execution has a valid narrative, fresh displacement, a clean imbalance entry, structural risk, and a defined liquidity target.",
      checklist_items: [
        { text: "Directional draw is clear before the setup", category: "entry", required: true, sort_order: 0 },
        { text: "Displacement created a valid FVG or IFVG", category: "confirmation", required: true, sort_order: 1 },
        { text: "Retrace preserves continuation structure", category: "confirmation", required: true, sort_order: 2 },
        { text: "Structural invalidation is defined", category: "risk", required: true, sort_order: 3 },
        { text: "Liquidity target is defined before entry", category: "management", required: true, sort_order: 4 },
      ],
    },
  },
  {
    key: "htf-pd-reaction",
    name: "HTF PD Array Reaction",
    short: "Use a 1H or 4H location as context, then require lower-timeframe proof before entry.",
    tags: ["1H / 4H", "PD array", "Reaction"],
    body: {
      name: "HTF PD Array Reaction",
      description: "A reaction setup around a meaningful higher-timeframe FVG or PD array with lower-timeframe confirmation.",
      active: true,
      market_scope: "Index futures",
      direction_scope: "both",
      preferred_session: "Any session",
      minimum_confluences: 3,
      ideal_entry_criteria: "Price reaches a meaningful 1H or 4H PD array or imbalance that fits the broader market narrative. Do not enter on touch alone. Wait for a lower-timeframe liquidity event, displacement, or structure shift that proves the area is reacting.",
      confirmation_criteria: "The higher-timeframe area is clearly defined and the 15m, 5m, or 1m execution layer shows a real response through displacement, inversion, or a confirmed liquidity rotation.",
      invalidation_criteria: "Price accepts through the higher-timeframe area or lower-timeframe confirmation fully fails.",
      stop_logic: "Place risk beyond the structure that proves the reaction wrong, not simply beyond the nearest candle.",
      target_logic: "Use local liquidity for a reaction trade. Use a broader opposing draw only when the higher-timeframe narrative supports continuation away from the area.",
      management_rules: "Separate a quick reaction from a full reversal. The location can be valid even when the correct trade horizon is short.",
      prohibited_conditions: "No blind touch entry. No assumption that every higher-timeframe FVG must reverse price. No oversized risk because the timeframe is higher.",
      default_grade_expectations: "A-grade execution respects the higher-timeframe location but waits for lower-timeframe proof and uses a target appropriate to the reaction strength.",
      checklist_items: [
        { text: "1H or 4H PD array is clearly defined", category: "entry", required: true, sort_order: 0 },
        { text: "Location fits the broader narrative", category: "entry", required: true, sort_order: 1 },
        { text: "Lower-timeframe reaction is confirmed", category: "confirmation", required: true, sort_order: 2 },
        { text: "Stop is beyond meaningful structural invalidation", category: "risk", required: true, sort_order: 3 },
        { text: "Target matches reaction or continuation horizon", category: "management", required: true, sort_order: 4 },
      ],
    },
  },
  {
    key: "rsi-divergence",
    name: "RSI Divergence Confirmation",
    short: "Use 5m or 15m divergence as supporting evidence, never as the setup by itself.",
    tags: ["5m / 15m", "Divergence", "Secondary"],
    body: {
      name: "RSI Divergence Confirmation",
      description: "A contextual reversal or rotation plan where RSI divergence supports an existing liquidity and structure thesis.",
      active: true,
      market_scope: "Index futures",
      direction_scope: "both",
      preferred_session: "Any session",
      minimum_confluences: 3,
      ideal_entry_criteria: "A valid liquidity or structural setup exists first. Prefer 5m or 15m divergence around a meaningful sweep, PD array, or exhaustion point. Higher-timeframe divergence can add context but does not create the entry by itself.",
      confirmation_criteria: "Divergence aligns with a real liquidity event, displacement, or structure change. Price confirms before entry.",
      invalidation_criteria: "Price continues through the structural level that supported the divergence thesis or the expected rotation fails to develop.",
      stop_logic: "Use structural invalidation from the price setup. Do not place the stop based on the oscillator.",
      target_logic: "Target the next meaningful liquidity objective supported by the price structure.",
      management_rules: "Treat divergence as secondary evidence. Price action and structure remain primary throughout the trade.",
      prohibited_conditions: "No entry because RSI diverged by itself. No repeated countertrend attempts while structure continues to deliver strongly in the original direction.",
      default_grade_expectations: "A-grade execution has a valid price setup first, useful divergence second, structural risk, and a clear target.",
      checklist_items: [
        { text: "Price setup exists without relying on RSI", category: "entry", required: true, sort_order: 0 },
        { text: "5m or 15m divergence supports the idea", category: "confirmation", required: false, sort_order: 1 },
        { text: "Liquidity or structure confirms the rotation", category: "confirmation", required: true, sort_order: 2 },
        { text: "Stop is based on price structure", category: "risk", required: true, sort_order: 3 },
        { text: "Target is based on liquidity or structure", category: "management", required: true, sort_order: 4 },
      ],
    },
  },
];

export default function PlaybooksPage() {
  const router = useRouter();
  const [items, setItems] = useState<Playbook[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [presetSaving, setPresetSaving] = useState("");
  const [query, setQuery] = useState("");

  const load = () => api<Playbook[]>("/playbooks")
    .then((value) => {
      setItems(value);
      setError("");
    })
    .catch((reason: Error) => setError(reason.message))
    .finally(() => setLoaded(true));

  useEffect(() => {
    void load();
  }, []);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return items;
    return items.filter((item) => `${item.name} ${item.description ?? ""} ${item.preferred_session ?? ""} ${item.direction_scope ?? ""}`.toLowerCase().includes(needle));
  }, [items, query]);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setSaving(true);
    try {
      const item = await api<Playbook>("/playbooks", {
        method: "POST",
        body: JSON.stringify({
          name: form.get("name"),
          description: form.get("description") || null,
          active: true,
          direction_scope: "both",
          checklist_items: [
            { text: "The setup matches the written entry criteria", category: "entry", required: true, sort_order: 0 },
            { text: "Risk and invalidation are defined", category: "risk", required: true, sort_order: 1 },
          ],
        }),
      });
      router.push(`/playbooks/${item.id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Playbook could not be created.");
    } finally {
      setSaving(false);
    }
  }

  async function createFromPreset(preset: PlaybookPreset) {
    const existing = items.find((item) => item.name.trim().toLowerCase() === preset.body.name.toLowerCase());
    if (existing) {
      router.push(`/playbooks/${existing.id}`);
      return;
    }
    setPresetSaving(preset.key);
    setError("");
    try {
      const item = await api<Playbook>("/playbooks", {
        method: "POST",
        body: JSON.stringify(preset.body),
      });
      router.push(`/playbooks/${item.id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Strategy could not be created.");
    } finally {
      setPresetSaving("");
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Plan library"
        title="Playbooks"
        description="Keep entry logic, invalidation, management, and checklist rules together."
        action={<button className="button primary" onClick={() => setCreating((value) => !value)}>{creating ? "Close form" : "Create playbook"}</button>}
      />
      {error && <ErrorState message={error} />}

      <section className="strategy-preset-section">
        <div className="strategy-preset-head">
          <div>
            <span className="eyebrow">Strategy starters</span>
            <h2>Start from the way you already trade</h2>
            <p>These fill the full plan and checklist. Open one, then change anything that does not match your exact rules.</p>
          </div>
        </div>
        <div className="strategy-preset-grid">
          {PLAYBOOK_PRESETS.map((preset) => {
            const existing = items.find((item) => item.name.trim().toLowerCase() === preset.body.name.toLowerCase());
            return (
              <article className="strategy-preset-card" key={preset.key}>
                <div className="strategy-preset-tags">{preset.tags.map((tag) => <span key={tag}>{tag}</span>)}</div>
                <h3>{preset.name}</h3>
                <p>{preset.short}</p>
                <button className="button" type="button" onClick={() => void createFromPreset(preset)} disabled={Boolean(presetSaving)}>
                  {existing ? "Open strategy" : presetSaving === preset.key ? "Creating..." : "Use strategy"}
                </button>
              </article>
            );
          })}
        </div>
      </section>

      {creating && <form className="card create-panel premium-create-panel" onSubmit={create}>
        <div className="field"><label htmlFor="playbook-name">Name</label><input id="playbook-name" name="name" required maxLength={160} autoFocus /></div>
        <div className="field"><label htmlFor="playbook-description">Description</label><textarea id="playbook-description" name="description" /></div>
        <button className="button primary" disabled={saving}>{saving ? "Creating..." : "Create and define plan"}</button>
      </form>}

      {items.length > 3 && (
        <div className="playbook-toolbar">
          <input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Find a playbook" aria-label="Find a playbook" />
          <span>{visible.length} of {items.length}</span>
        </div>
      )}

      {!loaded && !error ? (
        <Skeleton rows={5} />
      ) : !items.length ? (
        <EmptyState title="No saved playbooks yet." copy="Use one of the strategy starters above or create a plan from scratch." href="#" action="Create playbook" />
      ) : !visible.length ? (
        <EmptyState title="No playbooks match that search." copy="Try a different name, session, or direction." href="/playbooks" action="Clear search" />
      ) : (
        <section className="playbook-grid premium-playbook-grid">
          {visible.map((item) => {
            const coreRules = item.checklist_items.filter((check) => check.required).length;
            const definedSections = [
              item.ideal_entry_criteria,
              item.confirmation_criteria,
              item.invalidation_criteria,
              item.stop_logic,
              item.target_logic,
              item.management_rules,
            ].filter(Boolean).length;
            return (
              <Link href={`/playbooks/${item.id}`} className={`card playbook-card premium-playbook-card ${item.active ? "" : "archived"}`} key={item.id}>
                <div className="playbook-card-top">
                  <span className="eyebrow">{item.preferred_session ?? "Any session"}</span>
                  <span className={`playbook-state ${item.active ? "active" : "archived"}`}>{item.active ? "Active" : "Archived"}</span>
                </div>
                <h2>{item.name}</h2>
                <p>{item.description ?? "Add the purpose and context for this plan."}</p>
                <div className="playbook-fingerprint" aria-hidden="true">
                  {Array.from({ length: 6 }, (_, index) => <i className={index < definedSections ? "filled" : ""} key={index} />)}
                </div>
                <dl className="playbook-details">
                  <div><dt>Direction</dt><dd>{item.direction_scope ?? "Both"}</dd></div>
                  <div><dt>Checklist</dt><dd>{item.checklist_items.length} items</dd></div>
                  <div><dt>Core rules</dt><dd>{coreRules}</dd></div>
                </dl>
                <footer><span>{definedSections} plan sections defined</span><span>Open plan →</span></footer>
              </Link>
            );
          })}
        </section>
      )}
    </>
  );
}
