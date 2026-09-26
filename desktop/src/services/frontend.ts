import { ChildProcess, spawn } from "node:child_process";
import { connect } from "node:net";
import { join } from "node:path";
import { DesktopLogger } from "./logger";

export const JOURNALME_FRONTEND_PORT = 3066;
export const FRONTEND_URL = process.env.JOURNALME_FRONTEND_URL ?? `http://127.0.0.1:${JOURNALME_FRONTEND_PORT}`;

type FrontendHealth = { status?: unknown; product?: unknown; surface?: unknown };
type SpawnProcess = typeof spawn;

function parsedLocalUrl(value: string): URL {
  const url = new URL(value);
  if (!["127.0.0.1", "localhost", "[::1]"].includes(url.hostname)) throw new Error("JournalMe Desktop only loads a verified local JournalMe frontend.");
  return url;
}

function frontendPort(value: string): number {
  const url = parsedLocalUrl(value);
  return Number(url.port || (url.protocol === "https:" ? 443 : 80));
}

export function isSafeFrontendNavigation(target: string, frontendUrl: string): boolean {
  try { return new URL(target).origin === parsedLocalUrl(frontendUrl).origin; } catch { return false; }
}

export async function frontendIsJournalMe(url = FRONTEND_URL): Promise<boolean> {
  try {
    parsedLocalUrl(url);
    const response = await fetch(`${url.replace(/\/$/, "")}/api/desktop-health`, { signal: AbortSignal.timeout(1_500), headers: { Accept: "application/json" } });
    if (!response.ok) return false;
    const body = await response.json() as FrontendHealth;
    return body.status === "ok" && body.product === "JournalMe" && body.surface === "frontend";
  } catch { return false; }
}

export async function frontendPortIsOccupied(url = FRONTEND_URL): Promise<boolean> {
  try {
    const parsed = parsedLocalUrl(url);
    return await new Promise<boolean>((resolve) => {
      const socket = connect({ host: parsed.hostname, port: frontendPort(url) }); const done = (value: boolean) => { socket.removeAllListeners(); socket.destroy(); resolve(value); };
      socket.once("connect", () => done(true)); socket.once("error", () => done(false)); socket.setTimeout(1_000, () => done(false));
    });
  } catch { return false; }
}

export class FrontendManager {
  private child: ChildProcess | undefined;
  constructor(
    private readonly root: string,
    private readonly logger: DesktopLogger,
    private readonly development: boolean,
    private readonly frontendUrl = FRONTEND_URL,
    private readonly spawnProcess: SpawnProcess = spawn,
  ) {}

  async ensureRunning(): Promise<string> {
    parsedLocalUrl(this.frontendUrl);
    if (await frontendIsJournalMe(this.frontendUrl)) { this.logger.info("frontend.reused", { url: this.frontendUrl, verified: true }); return this.frontendUrl; }
    if (await frontendPortIsOccupied(this.frontendUrl)) { this.logger.error("frontend.port_conflict", { url: this.frontendUrl }); throw new Error(`Port conflict: ${this.frontendUrl} is occupied by an application that is not JournalMe.`); }
    this.startFrontend();
    for (let attempt = 0; attempt < 40; attempt += 1) {
      if (await frontendIsJournalMe(this.frontendUrl)) { this.logger.info("frontend.started", { url: this.frontendUrl, verified: true }); return this.frontendUrl; }
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
    this.stopOwned();
    throw new Error(`JournalMe frontend did not become ready at ${this.frontendUrl}.`);
  }

  stopOwned(): void { if (this.child && !this.child.killed) { this.logger.info("frontend.stopping", { url: this.frontendUrl }); this.child.kill(); } }
  get ownsFrontend(): boolean { return Boolean(this.child); }

  private startFrontend(): void {
    if (!this.development) {
      const server = join(process.resourcesPath, "frontend", "server.js"); this.logger.info("frontend.starting_packaged", { server, url: this.frontendUrl });
      this.child = this.spawnProcess(process.execPath, [server], { windowsHide: true, stdio: ["ignore", "pipe", "pipe"], env: { ...process.env, ELECTRON_RUN_AS_NODE: "1", HOSTNAME: "127.0.0.1", PORT: String(frontendPort(this.frontendUrl)) } });
    } else {
      const frontend = join(this.root, "frontend"); const npm = process.platform === "win32" ? "npm.cmd" : "npm"; this.logger.info("frontend.starting", { cwd: frontend, url: this.frontendUrl });
      this.child = this.spawnProcess(npm, ["run", "dev", "--", "--hostname", "127.0.0.1", "--port", String(frontendPort(this.frontendUrl))], { cwd: frontend, windowsHide: true, stdio: ["ignore", "pipe", "pipe"], env: { ...process.env, NEXT_PUBLIC_AUTH_MODE: "local", NEXT_PUBLIC_API_URL: "http://127.0.0.1:8066/api/v1", NEXT_PUBLIC_JOURNALME_API_URL: "http://127.0.0.1:8066/api/v1" } });
    }
    this.child.stdout?.on("data", (line: Buffer) => this.logger.info("frontend.stdout", { line: line.toString().trim().slice(0, 500) }));
    this.child.stderr?.on("data", (line: Buffer) => this.logger.error("frontend.stderr", { line: line.toString().trim().slice(0, 500) }));
    this.child.once("exit", (code) => { this.logger.error("frontend.exit", { code }); this.child = undefined; });
  }
}
