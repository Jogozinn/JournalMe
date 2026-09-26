import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";

export type DesktopConfig = {
  companionVisible: boolean;
  companionCollapsed: boolean;
  launchAtLogin: boolean;
  window?: { x?: number; y?: number; width: number; height: number };
};

export const DEFAULT_CONFIG: DesktopConfig = {
  companionVisible: true,
  companionCollapsed: true,
  launchAtLogin: false,
};

function validWindow(value: unknown): DesktopConfig["window"] {
  if (!value || typeof value !== "object") return undefined;
  const candidate = value as Record<string, unknown>;
  const width = Number(candidate.width);
  const height = Number(candidate.height);
  if (!Number.isFinite(width) || !Number.isFinite(height) || width < 600 || height < 400) {
    return undefined;
  }
  return {
    width: Math.round(width), height: Math.round(height),
    x: Number.isFinite(Number(candidate.x)) ? Math.round(Number(candidate.x)) : undefined,
    y: Number.isFinite(Number(candidate.y)) ? Math.round(Number(candidate.y)) : undefined,
  };
}

export function loadDesktopConfig(path: string): DesktopConfig {
  try {
    if (!existsSync(path)) return { ...DEFAULT_CONFIG };
    const parsed: unknown = JSON.parse(readFileSync(path, "utf8"));
    if (!parsed || typeof parsed !== "object") return { ...DEFAULT_CONFIG };
    const value = parsed as Record<string, unknown>;
    return {
      companionVisible: typeof value.companionVisible === "boolean" ? value.companionVisible : DEFAULT_CONFIG.companionVisible,
      companionCollapsed: typeof value.companionCollapsed === "boolean" ? value.companionCollapsed : DEFAULT_CONFIG.companionCollapsed,
      launchAtLogin: typeof value.launchAtLogin === "boolean" ? value.launchAtLogin : DEFAULT_CONFIG.launchAtLogin,
      window: validWindow(value.window),
    };
  } catch { return { ...DEFAULT_CONFIG }; }
}

export function saveDesktopConfig(path: string, value: DesktopConfig): void {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, JSON.stringify(value, null, 2), "utf8");
}

export function projectRoot(from: string = __dirname): string {
  return resolve(from, "..", "..");
}
