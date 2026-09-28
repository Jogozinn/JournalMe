"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { AccountProvider, useAccount } from "@/components/account-provider";
import { AuthProvider, useAuth } from "@/components/auth-provider";
import { BrandMark } from "@/components/brand-mark";
import { BrokerLiveActivity } from "@/components/broker-live-activity";
import { LearningNotifications } from "@/components/learning-notifications";
import { CommandPalette } from "@/components/command-palette";
import { Icon, type IconName } from "@/components/icons";
import { money } from "@/lib/api";

const nav: { href: string; label: string; icon: IconName }[] = [
  { href: "/", label: "Home", icon: "home" },
  { href: "/days", label: "Trading Days", icon: "days" },
  { href: "/trades", label: "Trades", icon: "trades" },
  { href: "/captures", label: "Captures", icon: "capture" },
  { href: "/calendar", label: "Calendar", icon: "calendar" },
  { href: "/analytics", label: "Analytics", icon: "analytics" },
  { href: "/intelligence", label: "Intelligence", icon: "intelligence" },
  { href: "/playbooks", label: "Playbooks", icon: "playbook" },
  { href: "/review", label: "Reviews", icon: "review" },
];

const utilityNav: { href: string; label: string; icon: IconName }[] = [
  { href: "/accounts", label: "Accounts", icon: "accounts" },
  { href: "/settings", label: "Settings", icon: "settings" },
];

const PUBLIC_AUTH_PATHS = new Set([
  "/login",
  "/register",
  "/forgot-password",
  "/reset-password",
]);

const AUTH_ENTRY_PATHS = new Set(["/login", "/register", "/forgot-password"]);
const PROTECTED_PREFIXES = [
  "/days",
  "/trades",
  "/captures",
  "/calendar",
  "/analytics",
  "/intelligence",
  "/playbooks",
  "/review",
  "/reviews",
  "/accounts",
  "/settings",
  "/import",
  "/imports",
  "/manual-trade",
  "/timeline",
  "/goals",
  "/more",
  "/companion",
];

function isProtectedPath(pathname: string): boolean {
  if (pathname === "/") return true;
  return PROTECTED_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}

function AccountSelect() {
  const { accounts, account, setAccountId } = useAccount();
  if (!accounts.length) return <span className="muted small">No account yet</span>;
  return (
    <select
      className="account-select"
      value={account?.id ?? ""}
      onChange={(event) => setAccountId(event.target.value)}
      aria-label="Trading account"
      title={account?.name ?? "Trading account"}
    >
      {accounts.map((item) => (
        <option key={item.id} value={item.id}>
          {item.name} · {money(item.current_balance, item.currency)}
        </option>
      ))}
    </select>
  );
}

function routeMatches(pathname: string, href: string): boolean {
  return pathname === href || (href !== "/" && pathname.startsWith(href));
}

function ShellContent({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { hosted, session, signOut } = useAuth();
  const { account } = useAccount();
  const [pendingPath, setPendingPath] = useState<string | null>(null);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [sidebarCompact, setSidebarCompact] = useState(false);

  useEffect(() => {
    const saved = window.localStorage.getItem("journalme-sidebar-compact");
    setSidebarCompact(saved === "1");
  }, []);

  function toggleSidebar() {
    setSidebarCompact((current) => {
      const next = !current;
      window.localStorage.setItem("journalme-sidebar-compact", next ? "1" : "0");
      return next;
    });
  }

  useEffect(() => {
    setMobileSidebarOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (!mobileSidebarOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMobileSidebarOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [mobileSidebarOpen]);

  useEffect(() => {
    const handleClick = (event: MouseEvent) => {
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const target = event.target;
      if (!(target instanceof Element)) return;
      const anchor = target.closest("a[href]") as HTMLAnchorElement | null;
      if (!anchor || anchor.target === "_blank" || anchor.hasAttribute("download")) return;
      const url = new URL(anchor.href, window.location.href);
      if (url.origin !== window.location.origin || url.pathname === pathname) return;
      setPendingPath(url.pathname);
    };
    document.addEventListener("click", handleClick, true);
    return () => document.removeEventListener("click", handleClick, true);
  }, [pathname]);

  useEffect(() => {
    setPendingPath(null);
  }, [pathname]);

  useEffect(() => {
    if (!pendingPath) return;
    const timeout = window.setTimeout(() => setPendingPath(null), 8000);
    return () => window.clearTimeout(timeout);
  }, [pendingPath]);

  const activePath = pendingPath ?? pathname;
  const userLabel = useMemo(
    () => (hosted ? session?.user.email ?? "Signed in" : "Local JournalMe"),
    [hosted, session],
  );

  return (
    <div
      className={`app-shell ${sidebarCompact ? "sidebar-compact" : ""} ${pendingPath ? "route-pending" : ""} ${mobileSidebarOpen ? "sidebar-mobile-open" : ""}`}
    >
      <div className="route-progress" aria-hidden="true" />
      <button className="sidebar-scrim" type="button" aria-label="Close navigation" onClick={() => setMobileSidebarOpen(false)} />
      <aside className="sidebar" aria-label="JournalMe navigation">
        <div className="sidebar-brand-row">
          <BrandMark />
          <button
            className="sidebar-toggle"
            type="button"
            aria-label={sidebarCompact ? "Expand navigation" : "Collapse navigation"}
            title={sidebarCompact ? "Expand navigation" : "Collapse navigation"}
            onClick={toggleSidebar}
          >
            <Icon name="panel" />
          </button>
        </div>
        <div className="sidebar-section-label">Journal</div>
        <nav aria-label="Primary navigation">
          {nav.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={routeMatches(activePath, item.href) ? "active" : ""}
              aria-current={routeMatches(activePath, item.href) ? "page" : undefined}
              title={item.label}
              onMouseEnter={() => router.prefetch(item.href)}
              onFocus={() => router.prefetch(item.href)}
            >
              <Icon name={item.icon} />
              <span>{item.label}</span>
            </Link>
          ))}
        </nav>
        <div className="sidebar-section-label workspace-label">Workspace</div>
        <nav className="utility-nav" aria-label="Workspace navigation">
          {utilityNav.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={routeMatches(activePath, item.href) ? "active" : ""}
              aria-current={routeMatches(activePath, item.href) ? "page" : undefined}
              title={item.label}
              onMouseEnter={() => router.prefetch(item.href)}
              onFocus={() => router.prefetch(item.href)}
            >
              <Icon name={item.icon} />
              <span>{item.label}</span>
            </Link>
          ))}
        </nav>
        <Link href="/import" className="button sidebar-import" onMouseEnter={() => router.prefetch("/import")} onFocus={() => router.prefetch("/import")} title="Import data">
          <Icon name="import" />
          <span>Import data</span>
        </Link>
        <button
          className="command-launch"
          type="button"
          onClick={() => window.dispatchEvent(new Event("journalme:open-command-palette"))}
        >
          <span><Icon name="search" /> Quick jump</span>
          <kbd>Ctrl K</kbd>
        </button>
        <Link
          href="/accounts"
          className="sidebar-account-compact"
          title={account?.name ?? "Accounts"}
          aria-label={account?.name ? `Current account: ${account.name}` : "Accounts"}
        >
          <Icon name="accounts" />
        </Link>
        <div className="sidebar-foot">
          <span className="sidebar-foot-label">Selected account</span>
          <AccountSelect />
          <div className="sidebar-user-row">
            <span title={userLabel}>{userLabel}</span>
            {hosted && (
              <button className="sidebar-signout" type="button" onClick={() => void signOut()}>
                Sign out
              </button>
            )}
          </div>
        </div>
      </aside>
      <div className="page-frame">
        <header className="mobile-header">
          <button className="mobile-menu-button" type="button" aria-label="Open navigation" onClick={() => setMobileSidebarOpen(true)}>
            <Icon name="menu" />
          </button>
          <BrandMark />
          <AccountSelect />
          {hosted && (
            <button className="button quiet" type="button" onClick={() => void signOut()}>
              Sign out
            </button>
          )}
        </header>
        <main><div className="route-view" key={pathname}>{children}</div></main>
      </div>
      <CommandPalette />
      <LearningNotifications />
      <BrokerLiveActivity />
      <nav className="bottom-nav" aria-label="Mobile navigation">
        {[nav[0], nav[1]].map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={routeMatches(activePath, item.href) ? "active" : ""}
          >
            <Icon name={item.icon} />
            <span>{item.label}</span>
          </Link>
        ))}
        <Link href="/import" className="import-action" aria-label="Import trading data">
          <Icon name="import" />
        </Link>
        <Link href="/calendar" className={routeMatches(activePath, "/calendar") ? "active" : ""}>
          <Icon name="calendar" />
          <span>Calendar</span>
        </Link>
        <Link href="/more" className={routeMatches(activePath, "/more") ? "active" : ""}>
          <Icon name="more" />
          <span>More</span>
        </Link>
      </nav>
    </div>
  );
}

function AuthenticatedShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { hosted, loading, session } = useAuth();
  const isPublicAuthPath = PUBLIC_AUTH_PATHS.has(pathname);

  useEffect(() => {
    if (!hosted) {
      if (AUTH_ENTRY_PATHS.has(pathname)) router.replace("/");
      return;
    }
    if (loading) return;
    if (!session && isProtectedPath(pathname)) router.replace("/login");
    if (session && AUTH_ENTRY_PATHS.has(pathname)) router.replace("/");
  }, [hosted, isPublicAuthPath, loading, pathname, router, session]);

  if (hosted && loading && isProtectedPath(pathname)) {
    return <main className="login-page"><p className="muted">Restoring your JournalMe session...</p></main>;
  }

  if (isPublicAuthPath) return <>{children}</>;

  if (hosted && !session && isProtectedPath(pathname)) {
    return <main className="login-page"><p className="muted">Opening sign in...</p></main>;
  }

  if (!isProtectedPath(pathname)) return <>{children}</>;

  return (
    <AccountProvider>
      <ShellContent>{children}</ShellContent>
    </AccountProvider>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <AuthenticatedShell>{children}</AuthenticatedShell>
    </AuthProvider>
  );
}
