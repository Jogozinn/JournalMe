"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

import {
  disableBackgroundPush,
  enableBackgroundPush,
  getLocalPushSubscription,
  getPushConfig,
  getPushPreferences,
  pushCapability,
  sendTestPush,
  type PushCapability,
  type PushConfig,
  type PushPreferences,
  updatePushPreferences,
} from "@/lib/push";

export function PushNotificationSettings({ compact = false }: { compact?: boolean }) {
  const [capability, setCapability] = useState<PushCapability | null>(null);
  const [config, setConfig] = useState<PushConfig | null>(null);
  const [preferences, setPreferences] = useState<PushPreferences | null>(null);
  const [currentDeviceSubscribed, setCurrentDeviceSubscribed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    setCapability(pushCapability());
    const [nextConfig, nextPreferences, localSubscription] = await Promise.all([
      getPushConfig(),
      getPushPreferences(),
      getLocalPushSubscription().catch(() => null),
    ]);
    setConfig(nextConfig);
    setPreferences(nextPreferences);
    setCurrentDeviceSubscribed(Boolean(localSubscription));
  }, []);

  useEffect(() => {
    void refresh().catch((reason: Error) => setError(reason.message));
  }, [refresh]);

  async function enable() {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await enableBackgroundPush();
      await sendTestPush();
      await refresh();
      setMessage("Background notifications are enabled. A test notification was sent to this device.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Notifications could not be enabled.");
    } finally {
      setBusy(false);
    }
  }

  async function disable() {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await disableBackgroundPush();
      await refresh();
      setMessage("Notifications are disabled on this device.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Notifications could not be disabled.");
    } finally {
      setBusy(false);
    }
  }

  async function test() {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await sendTestPush();
      setMessage("Test notification sent.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Test notification could not be sent.");
    } finally {
      setBusy(false);
    }
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!preferences) return;
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const next = await updatePushPreferences({
        enabled: form.get("enabled") === "on",
        patterns: form.get("patterns") === "on",
        mindset: form.get("mindset") === "on",
        review_reminders: form.get("review_reminders") === "on",
        daily_cue: form.get("daily_cue") === "on",
        daily_cue_time: String(form.get("daily_cue_time") || "08:30"),
        review_reminder_time: String(form.get("review_reminder_time") || "19:00"),
        quiet_hours_enabled: form.get("quiet_hours_enabled") === "on",
        quiet_hours_start: String(form.get("quiet_hours_start") || "22:00"),
        quiet_hours_end: String(form.get("quiet_hours_end") || "07:00"),
      });
      setPreferences(next);
      setMessage("Notification preferences saved.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Notification preferences could not be saved.");
    } finally {
      setBusy(false);
    }
  }

  if (!capability || !config || !preferences) {
    return <p className="muted small">Checking notification support…</p>;
  }

  const permission = capability.permission;
  const subscribed = currentDeviceSubscribed && permission === "granted";

  if (compact) {
    return (
      <div className="push-compact-settings">
        {capability.ios && !capability.standalone ? (
          <p>On iPhone, install JournalMe from Safari using <strong>Share → Add to Home Screen</strong>, then open the Home Screen app to enable notifications.</p>
        ) : !config.enabled ? (
          <p>Background push is waiting for the server VAPID keys to be configured.</p>
        ) : subscribed ? (
          <>
            <p><strong>Background notifications are on.</strong> JournalMe can notify this device while the app is closed.</p>
            <button className="button quiet compact" type="button" disabled={busy} onClick={() => void test()}>Send test</button>
          </>
        ) : (
          <button className="button quiet compact" type="button" disabled={busy} onClick={() => void enable()}>
            {busy ? "Enabling…" : "Enable background notifications"}
          </button>
        )}
        {message && <small className="positive">{message}</small>}
        {error && <small className="negative">{error}</small>}
      </div>
    );
  }

  return (
    <section className="card settings-panel push-settings" id="notifications">
      <div className="section-title">
        <div><p className="eyebrow">Notifications</p><h2>Learning that can reach you outside JournalMe</h2></div>
        <span className={subscribed ? "positive" : "muted"}>{subscribed ? "This device is subscribed" : `${preferences.active_subscriptions} subscribed device${preferences.active_subscriptions === 1 ? "" : "s"}`}</span>
      </div>
      <p className="muted">JournalMe only pushes evidence-backed patterns, your own carry-forward lesson, or unfinished review reminders. It does not generate trade signals.</p>
      {capability.ios && !capability.standalone && (
        <div className="notice"><strong>Install on iPhone first</strong><p>Open JournalMe in Safari, tap Share → Add to Home Screen, then launch JournalMe from its Home Screen icon. iOS allows Web Push from the installed app.</p></div>
      )}
      {!config.enabled && (
        <div className="notice warning"><strong>Server setup required</strong><p>VAPID keys are not configured on the backend yet. The deployment notes include the one-time setup command.</p></div>
      )}
      <div className="push-device-actions">
        {!subscribed ? (
          <button className="button primary" type="button" disabled={busy || !config.enabled || !capability.supported} onClick={() => void enable()}>
            {busy ? "Working…" : "Enable on this device"}
          </button>
        ) : (
          <>
            <button className="button" type="button" disabled={busy} onClick={() => void test()}>Send test notification</button>
            <button className="button quiet" type="button" disabled={busy} onClick={() => void disable()}>Disable on this device</button>
          </>
        )}
      </div>
      {message && <div className="notice success"><p>{message}</p></div>}
      {error && <div className="notice warning"><p>{error}</p></div>}
      <form className="push-preference-form" onSubmit={save}>
        <label className="switch-row"><input name="enabled" type="checkbox" defaultChecked={preferences.enabled} /> Allow JournalMe learning notifications</label>
        <label className="switch-row"><input name="patterns" type="checkbox" defaultChecked={preferences.patterns} /> New repeated/strong trading patterns</label>
        <label className="switch-row"><input name="mindset" type="checkbox" defaultChecked={preferences.mindset} /> Repeated mindset patterns from reviewed days</label>
        <label className="switch-row"><input name="review_reminders" type="checkbox" defaultChecked={preferences.review_reminders} /> Remind me about unfinished trade reviews</label>
        <div className="field push-time-field"><label>Review reminder time</label><input name="review_reminder_time" type="time" defaultValue={preferences.review_reminder_time} /></div>
        <label className="switch-row"><input name="daily_cue" type="checkbox" defaultChecked={preferences.daily_cue} /> Daily carry-forward cue from my own latest lesson</label>
        <div className="field push-time-field"><label>Daily cue time</label><input name="daily_cue_time" type="time" defaultValue={preferences.daily_cue_time} /></div>
        <label className="switch-row"><input name="quiet_hours_enabled" type="checkbox" defaultChecked={preferences.quiet_hours_enabled} /> Quiet hours</label>
        <div className="push-time-grid">
          <div className="field"><label>Quiet starts</label><input name="quiet_hours_start" type="time" defaultValue={preferences.quiet_hours_start} /></div>
          <div className="field"><label>Quiet ends</label><input name="quiet_hours_end" type="time" defaultValue={preferences.quiet_hours_end} /></div>
        </div>
        <button className="button primary" disabled={busy}>Save notification preferences</button>
      </form>
    </section>
  );
}
