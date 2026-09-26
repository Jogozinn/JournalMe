import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { getDesktopRuntimeMode } from "../src/runtime";

describe("desktop runtime mode", () => {
  it("defaults to safe local mode and rejects unimplemented cloud mode", () => {
    assert.equal(getDesktopRuntimeMode({}), "local");
    assert.throws(() => getDesktopRuntimeMode({ JOURNALME_DESKTOP_RUNTIME_MODE: "cloud" }), /not implemented/);
  });
});
