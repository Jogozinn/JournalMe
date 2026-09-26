import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { captureStatusMessage, PendingCaptureStore, validateCaptureMetadata, validateSaveRequest } from "../src/services/capture";

describe("capture payload", () => {
  it("builds compatible desktop metadata", () => {
    assert.deepEqual(validateCaptureMetadata({ event_type: "entry", symbol: " mnq ", side: "short", note: "test", setup_tags: ["FVG"], execution_tags: [], emotion_tags: [] }).symbol, "MNQ");
  });
  it("allows WAIT without a symbol and maps capture responses", () => {
    assert.equal(validateCaptureMetadata({ event_type: "wait", setup_tags: [], execution_tags: [], emotion_tags: [] }).symbol, undefined);
    assert.match(captureStatusMessage("matched"), /matched to trade/);
    assert.match(captureStatusMessage("suggested"), /possible trade match/);
    assert.match(captureStatusMessage("unmatched"), /waiting for trade import/);
  });
  it("retains a screenshot token until it is explicitly removed", () => {
    const store = new PendingCaptureStore(); const preview = store.add({ buffer: Buffer.from("image"), mime: "image/png", capturedAt: new Date().toISOString(), displayId: 1 });
    assert.match(preview.dataUrl, /^data:image\/png;base64,/); assert.equal(store.get(preview.token)?.buffer.toString(), "image"); store.remove(preview.token); assert.equal(store.get(preview.token), undefined);
  });
  it("rejects unsafe IPC save inputs", () => {
    assert.throws(() => validateSaveRequest({ token: "not-a-token", metadata: {} }), /Invalid screenshot token/);
  });
});
