# PWA / web readiness

Current: Next manifest defines standalone display, portrait orientation, maskable icon, theme colors, and start URL; layout declares Apple web-app metadata and `viewport-fit=cover`; CSS contains iPhone safe-area insets and mobile navigation spacing; the production-only service worker is registered through `PwaRegister`. Responsive UI and ordinary file uploads work in browser/PWA contexts.

Before hosted launch: configure `NEXT_PUBLIC_API_URL` to the HTTPS API origin, add that web origin to `JOURNALME_CORS_ORIGINS`, provide authenticated identity, verify photo/camera attachment UX on iOS Safari, set service-worker cache/version policy, and conduct install/touch-target testing. Offline database synchronization, background uploads, push notifications, and conflict resolution are intentionally deferred.
