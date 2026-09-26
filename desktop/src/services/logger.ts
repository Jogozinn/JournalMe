import { appendFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";

export class DesktopLogger {
  constructor(private readonly path: string) { mkdirSync(dirname(path), { recursive: true }); }
  info(event: string, detail?: Record<string, unknown>): void { this.write("INFO", event, detail); }
  error(event: string, detail?: Record<string, unknown>): void { this.write("ERROR", event, detail); }
  private write(level: string, event: string, detail?: Record<string, unknown>): void {
    const safe = detail ? ` ${JSON.stringify(detail)}` : "";
    appendFileSync(this.path, `${new Date().toISOString()} ${level} ${event}${safe}\n`);
  }
}

export function logPath(userData: string): string { return join(userData, "logs", "desktop.log"); }
