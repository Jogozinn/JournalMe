import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";
import { loadDesktopConfig, saveDesktopConfig } from "../src/config";

const folders: string[] = [];
afterEach(() => folders.splice(0).forEach((folder) => rmSync(folder, { recursive: true, force: true })));
describe("desktop config", () => {
  it("loads defaults and persists safe values", () => {
    const folder = mkdtempSync(join(tmpdir(), "journalme-desktop-")); folders.push(folder); const path = join(folder, "config.json");
    assert.equal(loadDesktopConfig(path).launchAtLogin, false);
    saveDesktopConfig(path, { companionVisible: false, companionCollapsed: true, launchAtLogin: true, window: { width: 1200, height: 800 } });
    assert.deepEqual(loadDesktopConfig(path), { launchAtLogin: true, companionVisible: false, companionCollapsed: true, window: { width: 1200, height: 800, x: undefined, y: undefined } });
  });
});
