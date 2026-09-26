import { ChildProcess, spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { DesktopLogger } from "./logger";

export const BACKEND_URL = "http://127.0.0.1:8066/api/v1";

export async function backendIsHealthy(url = BACKEND_URL): Promise<boolean> {
  try {
    const response = await fetch(`${url}/health`, { signal: AbortSignal.timeout(1_500) });
    if (!response.ok) return false;
    const body = await response.json() as { status?: string; product?: string };
    return body.status === "ok" && body.product === "JournalMe";
  } catch { return false; }
}

export class BackendManager {
  private child: ChildProcess | undefined;
  constructor(private readonly root: string, private readonly logger: DesktopLogger, private readonly healthUrl = BACKEND_URL, private readonly allowStart = true) {}
  async ensureRunning(): Promise<void> {
    if (await backendIsHealthy(this.healthUrl)) { this.logger.info("backend.reused"); return; }
    if (!this.allowStart) throw new Error("JournalMe backend is unavailable. Start the compatible local backend on port 8066.");
    const backend = join(this.root, "backend");
    const venvPython = join(this.root, ".venv", "Scripts", "python.exe");
    const python = existsSync(venvPython) ? venvPython : process.env.JOURNALME_PYTHON ?? "python";
    this.logger.info("backend.starting", { python, cwd: backend });
    this.child = spawn(python, ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8066"], {
      cwd: backend, windowsHide: true, stdio: ["ignore", "pipe", "pipe"],
    });
    this.child.stdout?.on("data", (line: Buffer) => this.logger.info("backend.stdout", { line: line.toString().trim().slice(0, 500) }));
    this.child.stderr?.on("data", (line: Buffer) => this.logger.error("backend.stderr", { line: line.toString().trim().slice(0, 500) }));
    this.child.once("exit", (code) => { this.logger.error("backend.exit", { code }); this.child = undefined; });
    for (let attempt = 0; attempt < 30; attempt += 1) {
      if (await backendIsHealthy(this.healthUrl)) { this.logger.info("backend.healthy", { owned: true }); return; }
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
    throw new Error("JournalMe backend did not become healthy on port 8066.");
  }
  stopOwned(): void { if (this.child && !this.child.killed) { this.logger.info("backend.stopping"); this.child.kill(); } }
  get ownsBackend(): boolean { return Boolean(this.child); }
}
