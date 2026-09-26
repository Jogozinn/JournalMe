import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { runInNewContext } from "node:vm";

import { describe, expect, it } from "vitest";

type ServiceWorkerEvent = {
  waitUntil: (promise: Promise<unknown>) => void;
};

describe("JournalMe service-worker cache cleanup", () => {
  it("deletes only stale JournalMe caches", async () => {
    const listeners = new Map<string, (event: ServiceWorkerEvent) => void>();
    const deleted: string[] = [];
    let cleanup: Promise<unknown> | undefined;
    const source = readFileSync(resolve(process.cwd(), "public", "sw.js"), "utf8");

    runInNewContext(source, {
      self: {
        addEventListener: (
          type: string,
          listener: (event: ServiceWorkerEvent) => void,
        ) => listeners.set(type, listener),
        clients: { claim: () => Promise.resolve() },
      },
      caches: {
        keys: () =>
          Promise.resolve([
            "journalme-static-v2",
            "journalme-shell-v1",
            "journalme-shell-v0",
            "waverr-shell-v1",
            "other-app",
          ]),
        delete: (key: string) => {
          deleted.push(key);
          return Promise.resolve(true);
        },
      },
      Promise,
    });

    listeners.get("activate")?.({
      waitUntil: (promise) => {
        cleanup = promise;
      },
    });
    await cleanup;

    expect(deleted).toEqual(["journalme-shell-v1", "journalme-shell-v0"]);
  });
});
