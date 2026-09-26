import assert from "node:assert/strict";
import { ChildProcess } from "node:child_process";
import { EventEmitter } from "node:events";
import { createServer, Server } from "node:http";
import { afterEach, describe, it } from "node:test";
import { frontendIsJournalMe, frontendPortIsOccupied, FrontendManager, isSafeFrontendNavigation } from "../src/services/frontend";

let server: Server | undefined;
const logger = { info: () => undefined, error: () => undefined } as never;

async function freePort(): Promise<number> {
  const probe = createServer(); await new Promise<void>((resolve) => probe.listen(0, "127.0.0.1", resolve));
  const address = probe.address(); const port = typeof address === "object" && address ? address.port : 0;
  await new Promise<void>((resolve) => probe.close(() => resolve())); return port;
}
function journalMeServer(): Server {
  return createServer((request, response) => {
    response.setHeader("Content-Type", "application/json");
    response.end(JSON.stringify(request.url === "/api/desktop-health" ? { status: "ok", product: "JournalMe", surface: "frontend" } : { status: "ok" }));
  });
}
function fakeChild(): ChildProcess & { killCount: number } {
  const child = new EventEmitter() as ChildProcess & { killCount: number };
  Object.assign(child, { killed: false, killCount: 0, kill() { this.killCount += 1; this.killed = true; return true; } });
  return child;
}
afterEach(async () => { if (server?.listening) await new Promise<void>((resolve) => server?.close(() => resolve())); server = undefined; });

describe("JournalMe frontend verification", () => {
  it("recognizes a healthy JournalMe frontend", async () => {
    server = journalMeServer(); await new Promise<void>((resolve) => server?.listen(0, "127.0.0.1", resolve)); const address = server.address();
    assert.equal(await frontendIsJournalMe(`http://127.0.0.1:${typeof address === "object" && address ? address.port : 0}`), true);
  });
  it("rejects a different local application on the expected port", async () => {
    server = createServer((_, response) => response.end(JSON.stringify({ status: "ok", product: "WaveRR" }))); await new Promise<void>((resolve) => server?.listen(0, "127.0.0.1", resolve)); const address = server.address(); const url = `http://127.0.0.1:${typeof address === "object" && address ? address.port : 0}`;
    let spawned = false; const manager = new FrontendManager(process.cwd(), logger, true, url, (() => { spawned = true; return fakeChild(); }) as never);
    assert.equal(await frontendIsJournalMe(url), false); assert.equal(await frontendPortIsOccupied(url), true); await assert.rejects(manager.ensureRunning(), /Port conflict/); assert.equal(spawned, false);
  });
  it("starts JournalMe when its dedicated port is absent and stops only its child", async () => {
    const port = await freePort(); const url = `http://127.0.0.1:${port}`; server = journalMeServer(); const child = fakeChild();
    let spawnedOptions: { env?: NodeJS.ProcessEnv } | undefined;
    const manager = new FrontendManager(process.cwd(), logger, true, url, ((...args: unknown[]) => { spawnedOptions = args[2] as { env?: NodeJS.ProcessEnv }; void server?.listen(port, "127.0.0.1"); return child; }) as never);
    assert.equal(await manager.ensureRunning(), url); assert.equal(manager.ownsFrontend, true); manager.stopOwned(); assert.equal(child.killCount, 1);
    assert.equal(spawnedOptions?.env?.NEXT_PUBLIC_AUTH_MODE, "local");
    assert.equal(spawnedOptions?.env?.NEXT_PUBLIC_JOURNALME_API_URL, "http://127.0.0.1:8066/api/v1");
  });
  it("reuses an externally-running verified JournalMe frontend", async () => {
    server = journalMeServer(); await new Promise<void>((resolve) => server?.listen(0, "127.0.0.1", resolve)); const address = server.address(); const url = `http://127.0.0.1:${typeof address === "object" && address ? address.port : 0}`;
    let spawned = false; const manager = new FrontendManager(process.cwd(), logger, true, url, (() => { spawned = true; return fakeChild(); }) as never);
    assert.equal(await manager.ensureRunning(), url); assert.equal(manager.ownsFrontend, false); manager.stopOwned(); assert.equal(spawned, false);
  });
  it("never permits an incorrect localhost application as a full-window navigation", () => {
    const url = "http://127.0.0.1:3066";
    assert.equal(isSafeFrontendNavigation(`${url}/trades`, url), true);
    assert.equal(isSafeFrontendNavigation("http://127.0.0.1:3000", url), false);
    assert.equal(isSafeFrontendNavigation("http://127.0.0.1:3066.evil.test", url), false);
  });
});
