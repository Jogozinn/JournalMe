import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.fn();

vi.mock("@/lib/api", () => ({ api }));

import { AccountProvider, useAccount } from "@/components/account-provider";

const account = (id: string) => ({
  id,
  name: `Account ${id}`,
  external_account_id: null,
  provider: "fixture",
  account_type: "funded",
  starting_balance: "50000",
  timezone: "America/New_York",
  currency: "USD",
  active: true,
  lifecycle_status: "active" as const,
  notes: null,
  current_balance: "50000",
  net_pnl: "0",
  configuration_required: false,
  active_plan: null,
  balance_resolution: {
    starting_balance: "50000",
    imported_balance: null,
    imported_balance_as_of: null,
    calculated_balance: null,
    calculated_balance_as_of: null,
    resolved_current_balance: "50000",
    resolution_method: "starting_balance",
    reconciliation_difference: null,
    stale_snapshot: false,
  },
});

function CurrentAccountProbe() {
  const { account: current, refresh } = useAccount();
  return <><span>{current?.id ?? "none"}</span><button onClick={() => void refresh()}>Refresh</button></>;
}

describe("account selection", () => {
  beforeEach(() => {
    api.mockReset();
    window.localStorage.clear();
  });

  it("falls back to another active account when the stored current account is archived", async () => {
    window.localStorage.setItem("journalme-account", "archived-account");
    api.mockResolvedValueOnce([account("archived-account"), account("active-account")]);
    api.mockResolvedValueOnce([account("active-account")]);
    render(<AccountProvider><CurrentAccountProbe /></AccountProvider>);

    await waitFor(() => expect(screen.getByText("archived-account")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(screen.getByText("active-account")).toBeInTheDocument());
    expect(window.localStorage.getItem("journalme-account")).toBe("active-account");
  });
});
