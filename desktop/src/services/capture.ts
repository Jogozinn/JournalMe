import { randomUUID } from "node:crypto";
import { CaptureMetadata, CaptureResult, CaptureEventType, ScreenshotPreview } from "../types";

const EVENT_TYPES = new Set<CaptureEventType>(["entry", "exit", "update", "wait"]);
const MAX_TAGS = 40;
const MAX_IMAGE_BYTES = 10 * 1024 * 1024;

type StoredImage = { buffer: Buffer; mime: "image/png" | "image/jpeg"; capturedAt: string; displayId: number; expiresAt: number };

export class PendingCaptureStore {
  private readonly images = new Map<string, StoredImage>();
  add(image: Omit<StoredImage, "expiresAt">): ScreenshotPreview {
    this.purge(); const token = randomUUID();
    this.images.set(token, { ...image, expiresAt: Date.now() + 30 * 60_000 });
    return { token, dataUrl: `data:${image.mime};base64,${image.buffer.toString("base64")}`, capturedAt: image.capturedAt, displayId: image.displayId };
  }
  get(token: string): StoredImage | undefined { this.purge(); return this.images.get(token); }
  remove(token: string): void { this.images.delete(token); }
  private purge(): void { for (const [token, item] of this.images) if (item.expiresAt < Date.now()) this.images.delete(token); }
}

function stringList(value: unknown, name: string): string[] {
  if (!Array.isArray(value)) throw new Error(`${name} must be a list.`);
  const values = value.filter((item): item is string => typeof item === "string").map((item) => item.trim()).filter(Boolean);
  if (values.length !== value.length || values.length > MAX_TAGS || values.some((item) => item.length > 80)) throw new Error(`Invalid ${name}.`);
  return [...new Set(values)];
}

export function validateCaptureMetadata(value: unknown): CaptureMetadata {
  if (!value || typeof value !== "object") throw new Error("Capture metadata is required.");
  const raw = value as Record<string, unknown>; const eventType = String(raw.event_type ?? "").toLowerCase() as CaptureEventType;
  if (!EVENT_TYPES.has(eventType)) throw new Error("Invalid capture event type.");
  const symbol = typeof raw.symbol === "string" ? raw.symbol.trim().toUpperCase().slice(0, 80) : "";
  if (eventType !== "wait" && !symbol) throw new Error("A symbol is required for this capture.");
  const side = raw.side === "long" || raw.side === "short" ? raw.side : undefined;
  const note = typeof raw.note === "string" ? raw.note.trim().slice(0, 1000) : "";
  if (typeof raw.note === "string" && raw.note.length > 1000) throw new Error("Note may contain at most 1000 characters.");
  return { event_type: eventType, captured_at: typeof raw.captured_at === "string" ? raw.captured_at : new Date().toISOString(), symbol: symbol || undefined, side, note: note || undefined, setup_tags: stringList(raw.setup_tags ?? [], "setup tags"), execution_tags: stringList(raw.execution_tags ?? [], "execution tags"), emotion_tags: stringList(raw.emotion_tags ?? [], "emotion tags"), source: "journalme_desktop", platform: process.platform };
}

export function validateSaveRequest(value: unknown): { token: string; metadata: CaptureMetadata } {
  if (!value || typeof value !== "object") throw new Error("Invalid capture save request.");
  const raw = value as { token?: unknown; metadata?: unknown };
  if (typeof raw.token !== "string" || !/^[0-9a-f-]{36}$/i.test(raw.token)) throw new Error("Invalid screenshot token.");
  return { token: raw.token, metadata: validateCaptureMetadata(raw.metadata) };
}

export async function postCapture(apiUrl: string, metadata: CaptureMetadata, image: StoredImage): Promise<CaptureResult> {
  if (image.buffer.length > MAX_IMAGE_BYTES) throw new Error("Screenshot is too large to save.");
  const form = new FormData(); form.set("metadata", JSON.stringify(metadata));
  const bytes = image.buffer.buffer.slice(image.buffer.byteOffset, image.buffer.byteOffset + image.buffer.byteLength) as ArrayBuffer;
  form.set("screenshot", new Blob([bytes], { type: image.mime }), `journalme-${Date.now()}.${image.mime === "image/png" ? "png" : "jpg"}`);
  const response = await fetch(`${apiUrl}/captures`, { method: "POST", body: form, signal: AbortSignal.timeout(20_000) });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : "JournalMe could not save the capture.");
  return body as CaptureResult;
}

export function captureStatusMessage(status: string): string {
  if (status === "matched") return "Saved and matched to trade";
  if (status === "suggested") return "Saved — possible trade match";
  return "Saved — waiting for trade import/match";
}
