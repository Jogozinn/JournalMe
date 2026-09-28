const CACHE = "journalme-static-v5";
const STATIC = [
  "/brand/journalme-app-icon-192.png",
  "/brand/journalme-app-icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(STATIC)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key.startsWith("journalme-") && key !== CACHE)
          .map((key) => caches.delete(key)),
      ),
    ),
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  const url = new URL(event.request.url);
  if (
    url.origin !== self.location.origin ||
    url.pathname.startsWith("/_next/") ||
    url.pathname.includes("/api/") ||
    event.request.mode === "navigate"
  ) {
    return;
  }
  if (STATIC.includes(url.pathname)) {
    event.respondWith(caches.match(event.request).then((cached) => cached || fetch(event.request)));
  }
});

self.addEventListener("push", (event) => {
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch {
    payload = { body: event.data ? event.data.text() : "JournalMe has something new for you." };
  }
  const title = payload.title || "JournalMe";
  event.waitUntil(
    self.registration.showNotification(title, {
      body: payload.body || "JournalMe has something new for you.",
      icon: "/brand/journalme-app-icon-192.png",
      badge: "/brand/journalme-app-icon-192.png",
      tag: payload.tag || "journalme-learning",
      data: { url: payload.url || "/intelligence", kind: payload.kind || "learning" },
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = new URL(event.notification.data?.url || "/intelligence", self.location.origin).href;
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
      const existing = windows.find((client) => "focus" in client);
      if (existing) {
        existing.navigate(target);
        return existing.focus();
      }
      return self.clients.openWindow(target);
    }),
  );
});
