import { describe, expect, it } from "vitest";

import {
  tradovateHasBalanceReport,
  tradovateQuickSyncMissing,
  type BrokerImportPreview,
} from "@/lib/broker-sync";

function preview(types: string[]): BrokerImportPreview {
  return {
    session_id: "session",
    status: "ready",
    reports: types.map((type) => ({
      filename: `${type}.csv`,
      type,
      rows: 1,
      duplicate_rows: 0,
      status: "recognized",
    })),
    coverage: { start: null, end: null },
    canonical_trades: 1,
    new_trades: 1,
    existing_trades: 0,
    warnings: [],
    errors: [],
  };
}

describe("Tradovate Quick Sync requirements", () => {
  it("accepts Performance and Fills as the core pair", () => {
    expect(tradovateQuickSyncMissing(preview(["performance", "fills"]))).toEqual([]);
  });

  it("accepts Position History as the paired-trade source", () => {
    expect(tradovateQuickSyncMissing(preview(["position_history", "fills"]))).toEqual([]);
  });

  it("reports missing core files and recognizes balance history", () => {
    const value = preview(["account_balance_history"]);
    expect(tradovateQuickSyncMissing(value)).toEqual(["Performance", "Fills"]);
    expect(tradovateHasBalanceReport(value)).toBe(true);
  });
});
