"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { useAccount } from "@/components/account-provider";
import { Icon, type IconName } from "@/components/icons";

type Command = {
  label: string;
  hint: string;
  href: string;
  icon: IconName;
  keywords: string;
};

export function CommandPalette() {
  const router = useRouter();
  const pathname = usePathname();
  const { account } = useAccount();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const today = useMemo(() => new Date().toISOString().slice(0, 10), []);
  const commands = useMemo<Command[]>(() => [
    { label: "Home", hint: "Account pulse", href: "/", icon: "home", keywords: "dashboard overview balance pnl" },
    { label: "Trading days", hint: "Session archive", href: "/days", icon: "days", keywords: "days sessions journal" },
    { label: "Trades", hint: "Execution history", href: "/trades", icon: "trades", keywords: "trades executions fills" },
    { label: "Captures", hint: "Companion screenshots", href: "/captures", icon: "capture", keywords: "captures screenshots companion chart" },
    { label: "Calendar", hint: "Trading map", href: "/calendar", icon: "calendar", keywords: "calendar month pnl" },
    { label: "Analytics", hint: "Pattern scan", href: "/analytics", icon: "analytics", keywords: "analytics patterns stats" },
    { label: "Playbooks", hint: "Plan library", href: "/playbooks", icon: "playbook", keywords: "playbooks setup rules" },
    { label: "Reviews", hint: "Clear the queue", href: "/review", icon: "review", keywords: "review queue practice" },
    { label: "Open today", hint: "Plan or review this session", href: `/timeline/${today}`, icon: "journal", keywords: "today journal session plan" },
    { label: "Add manual trade", hint: "Record an execution", href: "/manual-trade", icon: "trades", keywords: "manual trade add" },
    { label: "Import data", hint: "Bring in reports", href: "/import", icon: "import", keywords: "import csv data" },
    { label: "Accounts", hint: account?.name ?? "Manage accounts", href: "/accounts", icon: "accounts", keywords: "accounts switch prop" },
    { label: "Settings", hint: "Preferences and data", href: "/settings", icon: "settings", keywords: "settings preferences" },
  ], [account?.name, today]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return commands;
    return commands.filter((command) => `${command.label} ${command.hint} ${command.keywords}`.toLowerCase().includes(needle));
  }, [commands, query]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen((value) => !value);
      }
      if (!open) return;
      if (event.key === "Escape") {
        event.preventDefault();
        setOpen(false);
      }
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setActive((value) => Math.min(value + 1, Math.max(filtered.length - 1, 0)));
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        setActive((value) => Math.max(value - 1, 0));
      }
      if (event.key === "Enter" && filtered[active]) {
        event.preventDefault();
        router.push(filtered[active].href);
        setOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active, filtered, open, router]);

  useEffect(() => {
    const openPalette = () => setOpen(true);
    window.addEventListener("journalme:open-command-palette", openPalette);
    return () => window.removeEventListener("journalme:open-command-palette", openPalette);
  }, []);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setActive(0);
    const frame = window.requestAnimationFrame(() => inputRef.current?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, [open]);

  useEffect(() => setOpen(false), [pathname]);
  useEffect(() => setActive(0), [query]);

  if (!open) return null;

  return (
    <div className="command-backdrop" role="presentation" onMouseDown={() => setOpen(false)}>
      <section className="command-palette" role="dialog" aria-modal="true" aria-label="JournalMe command palette" onMouseDown={(event) => event.stopPropagation()}>
        <div className="command-search">
          <Icon name="search" />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Jump anywhere in JournalMe"
            aria-label="Search JournalMe commands"
          />
          <kbd>Esc</kbd>
        </div>
        <div className="command-results">
          {filtered.length ? filtered.map((command, index) => (
            <button
              type="button"
              className={index === active ? "active" : ""}
              key={`${command.href}-${command.label}`}
              onMouseEnter={() => {
                setActive(index);
                router.prefetch(command.href);
              }}
              onFocus={() => router.prefetch(command.href)}
              onClick={() => {
                router.push(command.href);
                setOpen(false);
              }}
            >
              <span className="command-icon"><Icon name={command.icon} /></span>
              <span><strong>{command.label}</strong><small>{command.hint}</small></span>
              <span className="command-arrow">↗</span>
            </button>
          )) : <p className="command-empty">No matching command.</p>}
        </div>
        <footer className="command-footer">
          <span>↑ ↓ to move</span><span>Enter to open</span><span>Esc to close</span>
        </footer>
      </section>
    </div>
  );
}
