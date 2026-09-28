"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useAccount } from "@/components/account-provider";
import { Icon } from "@/components/icons";
import { PushNotificationSettings } from "@/components/push-notification-settings";
import { api } from "@/lib/api";
import {
  buildLearningNotices,
  type LearningOverview,
  type ReviewReminderSummary,
} from "@/lib/learning";

export function LearningNotifications() {
  const { account } = useAccount();
  const [overview, setOverview] = useState<LearningOverview | null>(null);
  const [review, setReview] = useState<ReviewReminderSummary | null>(null);
  const [open, setOpen] = useState(false);

  const refresh = useCallback(async () => {
    if (!account) return;
    const params = new URLSearchParams({ current_account_id: account.id });
    const [learningResult, reviewResult] = await Promise.allSettled([
      api<LearningOverview>(`/intelligence/overview?${params.toString()}`, { cache: "reload" }),
      api<ReviewReminderSummary>(`/review-summary?account_id=${account.id}`, { cache: "reload" }),
    ]);
    if (learningResult.status === "fulfilled") setOverview(learningResult.value);
    if (reviewResult.status === "fulfilled") setReview(reviewResult.value);
  }, [account]);

  useEffect(() => {
    setOverview(null);
    setReview(null);
    setOpen(false);
    if (!account) return;
    void refresh();
    const timer = window.setInterval(() => void refresh(), 60_000);
    return () => window.clearInterval(timer);
  }, [account, refresh]);

  const notices = useMemo(() => buildLearningNotices(overview, review), [overview, review]);

  useEffect(() => {
    const badgeNavigator = navigator as Navigator & {
      setAppBadge?: (count?: number) => Promise<void>;
      clearAppBadge?: () => Promise<void>;
    };
    if (!badgeNavigator.setAppBadge) return;
    if (notices.length) void badgeNavigator.setAppBadge(notices.length).catch(() => undefined);
    else if (badgeNavigator.clearAppBadge) void badgeNavigator.clearAppBadge().catch(() => undefined);
  }, [notices.length]);

  if (!account) return null;

  return (
    <div className="learning-notification-shell">
      {open && (
        <section className="learning-notification-panel" aria-label="JournalMe learning notifications">
          <header>
            <div><strong>JournalMe noticed</strong><small>Only patterns supported by your stored trading data</small></div>
            <Link href="/intelligence" onClick={() => setOpen(false)}>Open Intelligence</Link>
          </header>
          <div className="learning-notification-list">
            {notices.length ? notices.map((notice) => (
              <Link href={notice.href} key={notice.key} onClick={() => setOpen(false)}>
                <span className={`learning-notice-dot ${notice.kind}`} aria-hidden="true" />
                <div><strong>{notice.title}</strong><p>{notice.body}</p></div>
              </Link>
            )) : <p className="muted small">Keep journaling. JournalMe will surface a reminder when the evidence is strong enough to be useful.</p>}
          </div>
          <footer>
            <PushNotificationSettings compact />
            <Link className="notification-settings-link" href="/settings#notifications" onClick={() => setOpen(false)}>Notification settings</Link>
          </footer>
        </section>
      )}
      <button
        className="learning-notification-button"
        type="button"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        aria-label={`JournalMe learning notifications${notices.length ? `, ${notices.length} available` : ""}`}
      >
        <Icon name="notification" />
        {notices.length > 0 && <span>{notices.length}</span>}
      </button>
    </div>
  );
}
