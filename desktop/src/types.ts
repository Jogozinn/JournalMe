export type CaptureEventType = "entry" | "exit" | "update" | "wait";
export type CaptureSide = "long" | "short";
export type MatchStatus = "matched" | "suggested" | "unmatched";

export type CaptureMetadata = {
  event_type: CaptureEventType;
  captured_at: string;
  symbol?: string;
  side?: CaptureSide;
  note?: string;
  setup_tags: string[];
  execution_tags: string[];
  emotion_tags: string[];
  source: "journalme_desktop";
  platform?: string;
};

export type CaptureResult = {
  id: string;
  captured_at: string;
  event_type: CaptureEventType;
  symbol: string | null;
  note: string | null;
  match_status: MatchStatus;
  matched_trade_id: string | null;
};

export type ScreenshotPreview = {
  token: string;
  dataUrl: string;
  capturedAt: string;
  displayId: number;
};
