import { createServer } from "node:http";
import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";
import { backendIsHealthy, BackendManager } from "../src/services/backend";

let server: ReturnType<typeof createServer> | undefined;
afterEach(async () => { await new Promise<void>((resolve) => server?.close(() => resolve()) ?? resolve()); });
describe("backend health detection", () => {
  it("accepts only JournalMe's health response", async () => {
    server = createServer((_, response) => { response.setHeader("Content-Type", "application/json"); response.end(JSON.stringify({ status: "ok", product: "JournalMe" })); });
    await new Promise<void>((resolve) => server?.listen(0, "127.0.0.1", resolve)); const address = server.address();
    assert.equal(await backendIsHealthy(`http://127.0.0.1:${typeof address === "object" && address ? address.port : 0}`), true);
  });
  it("does not start a duplicate when JournalMe is already healthy", async () => {
    server = createServer((_, response) => { response.setHeader("Content-Type", "application/json"); response.end(JSON.stringify({ status: "ok", product: "JournalMe" })); });
    await new Promise<void>((resolve) => server?.listen(0, "127.0.0.1", resolve)); const address = server.address(); const port = typeof address === "object" && address ? address.port : 0;
    const logger = { info: () => undefined, error: () => undefined } as never;
    const manager = new BackendManager(process.cwd(), logger, `http://127.0.0.1:${port}`);
    await manager.ensureRunning(); assert.equal(manager.ownsBackend, false);
  });
});
