"use client";

import { useEffect } from "react";

export function PwaRegister() {
  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;

    if (process.env.NODE_ENV !== "production") {
      // A production worker can continue controlling localhost after switching
      // back to `next dev`. Remove it and its JournalMe caches so development
      // can never mix old route chunks/CSS with a new build.
      void navigator.serviceWorker.getRegistrations().then((registrations) =>
        Promise.all(
          registrations
            .filter((registration) => registration.scope.startsWith(window.location.origin))
            .map((registration) => registration.unregister()),
        ),
      );
      if ("caches" in window) {
        void caches.keys().then((keys) =>
          Promise.all(
            keys.filter((key) => key.startsWith("journalme-")).map((key) => caches.delete(key)),
          ),
        );
      }
      return;
    }

    void navigator.serviceWorker.register("/sw.js", { updateViaCache: "none" });
  }, []);
  return null;
}
