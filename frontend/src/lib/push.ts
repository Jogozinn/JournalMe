import { api } from "@/lib/api";

export type PushConfig = {
  enabled: boolean;
  vapid_public_key: string | null;
};

export type PushPreferences = {
  enabled: boolean;
  patterns: boolean;
  mindset: boolean;
  review_reminders: boolean;
  daily_cue: boolean;
  daily_cue_time: string;
  review_reminder_time: string;
  quiet_hours_enabled: boolean;
  quiet_hours_start: string;
  quiet_hours_end: string;
  active_subscriptions: number;
};

export type PushCapability = {
  supported: boolean;
  ios: boolean;
  standalone: boolean;
  permission: NotificationPermission | "unsupported";
};

export function pushCapability(): PushCapability {
  if (typeof window === "undefined") {
    return { supported: false, ios: false, standalone: false, permission: "unsupported" };
  }
  const ios = /iPad|iPhone|iPod/.test(navigator.userAgent);
  const standalone =
    window.matchMedia?.("(display-mode: standalone)").matches === true ||
    Boolean((navigator as Navigator & { standalone?: boolean }).standalone);
  const supported =
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window &&
    (!ios || standalone);
  return {
    supported,
    ios,
    standalone,
    permission: "Notification" in window ? Notification.permission : "unsupported",
  };
}

export function urlBase64ToUint8Array(value: string): Uint8Array {
  const padding = "=".repeat((4 - (value.length % 4)) % 4);
  const base64 = (value + padding).replaceAll("-", "+").replaceAll("_", "/");
  const raw = window.atob(base64);
  return Uint8Array.from(raw, (char) => char.charCodeAt(0));
}

export async function getPushConfig(): Promise<PushConfig> {
  return api<PushConfig>("/push/config", { cache: "reload" });
}

export async function getPushPreferences(): Promise<PushPreferences> {
  return api<PushPreferences>("/push/preferences", { cache: "reload" });
}

export async function updatePushPreferences(
  changes: Partial<Omit<PushPreferences, "active_subscriptions">>,
): Promise<PushPreferences> {
  return api<PushPreferences>("/push/preferences", {
    method: "PUT",
    body: JSON.stringify(changes),
  });
}

async function activeRegistration(): Promise<ServiceWorkerRegistration> {
  const existing = await navigator.serviceWorker.getRegistration();
  if (existing) return existing;
  return navigator.serviceWorker.register("/sw.js", { updateViaCache: "none" });
}


export async function getLocalPushSubscription(): Promise<PushSubscription | null> {
  if (!("serviceWorker" in navigator)) return null;
  const registration = await navigator.serviceWorker.getRegistration();
  return registration?.pushManager.getSubscription() ?? null;
}

export async function enableBackgroundPush(deviceLabel?: string): Promise<PushSubscription> {
  const capability = pushCapability();
  if (!capability.supported) {
    throw new Error(
      capability.ios && !capability.standalone
        ? "On iPhone or iPad, add JournalMe to the Home Screen and open it there before enabling notifications."
        : "Background notifications are not supported in this browser.",
    );
  }
  const config = await getPushConfig();
  if (!config.enabled || !config.vapid_public_key) {
    throw new Error("JournalMe background notifications are not configured on the server yet.");
  }
  const permission = await Notification.requestPermission();
  if (permission !== "granted") {
    throw new Error("Notification permission was not granted.");
  }
  const registration = await activeRegistration();
  let subscription = await registration.pushManager.getSubscription();
  if (!subscription) {
    subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(config.vapid_public_key) as BufferSource,
    });
  }
  const serialized = subscription.toJSON();
  if (!serialized.endpoint || !serialized.keys?.p256dh || !serialized.keys?.auth) {
    throw new Error("The browser returned an incomplete push subscription.");
  }
  await api("/push/subscriptions", {
    method: "POST",
    body: JSON.stringify({
      endpoint: serialized.endpoint,
      keys: serialized.keys,
      device_label: deviceLabel ?? (capability.ios ? "iPhone/iPad Home Screen" : "Browser/PWA"),
      user_agent: navigator.userAgent,
    }),
  });
  return subscription;
}

export async function disableBackgroundPush(): Promise<void> {
  if (!("serviceWorker" in navigator)) return;
  const registration = await navigator.serviceWorker.getRegistration();
  const subscription = await registration?.pushManager.getSubscription();
  if (subscription) {
    await api("/push/subscriptions", {
      method: "DELETE",
      body: JSON.stringify({ endpoint: subscription.endpoint }),
    }).catch(() => undefined);
    await subscription.unsubscribe();
  }
}

export async function sendTestPush(): Promise<{ sent: number; failed: number; disabled: number }> {
  return api("/push/test", { method: "POST" });
}
