import { api } from "@/lib/api";

export type BrokerImportPreview = {
  session_id: string;
  status: string;
  reports: {
    filename: string;
    type: string;
    rows: number;
    duplicate_rows: number;
    status: string;
  }[];
  coverage: { start: string | null; end: string | null };
  canonical_trades: number;
  new_trades: number;
  existing_trades: number;
  warnings: string[];
  errors: unknown[];
};

export type BrokerSyncResult = {
  preview: BrokerImportPreview;
  created: {
    trades: number;
    fills: number;
    orders: number;
    cash_transactions: number;
    daily_balances: number;
  };
};

export function tradovateQuickSyncMissing(preview: BrokerImportPreview): string[] {
  const reportTypes = new Set(preview.reports.map((report) => report.type));
  const missing: string[] = [];
  if (!reportTypes.has("performance") && !reportTypes.has("position_history")) {
    missing.push("Performance");
  }
  if (!reportTypes.has("fills")) missing.push("Fills");
  return missing;
}

export function tradovateHasBalanceReport(preview: BrokerImportPreview): boolean {
  return preview.reports.some((report) => report.type === "account_balance_history");
}

export async function syncTradovateReports(
  files: File[],
  accountId: string | null,
): Promise<BrokerSyncResult> {
  const form = new FormData();
  files.forEach((file) => form.append("files", file));
  const query = accountId ? `?account_id=${encodeURIComponent(accountId)}` : "";
  const preview = await api<BrokerImportPreview>(`/imports/preview${query}`, {
    method: "POST",
    body: form,
  });

  const missing = tradovateQuickSyncMissing(preview);
  if (missing.length || preview.errors.length) {
    await api(`/imports/${preview.session_id}/cancel`, { method: "POST" }).catch(() => undefined);
    if (missing.length) {
      throw new Error(`Quick Sync needs ${missing.join(" and ")} report${missing.length === 1 ? "" : "s"}.`);
    }
    throw new Error("JournalMe found a validation error in the selected Tradovate reports.");
  }

  const commit = await api<{ created: BrokerSyncResult["created"] }>(
    `/imports/${preview.session_id}/commit`,
    { method: "POST" },
  );
  return { preview, created: commit.created };
}
