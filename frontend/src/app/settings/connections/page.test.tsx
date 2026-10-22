import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ConnectionsPage from "./page";

const api = vi.fn();
vi.mock("@/lib/api", () => ({ API_BASE_URL: "https://example.test/api/v1", api: (...args: unknown[]) => api(...args) }));
vi.mock("@/components/account-provider", () => ({ useAccount: () => ({ accounts: [{ id: "journal-1", name: "Lucid #1" }] }) }));
vi.mock("@/components/ui", () => ({ ErrorState: ({ message }: { message: string }) => <p>{message}</p>, Skeleton: () => <p>Loading</p> }));

const installation = { id: "install-1234", account_id: null, installation_id: null, provider: "ninjatrader", connection_type: "bridge_installation", display_name: "NinjaTrader installation", status: "connected", source_namespace: null, source_account_name: null, bridge_key_configured: true, bridge_token_created_at: null, last_seen_at: "2026-10-20T12:00:00Z", last_sync_at: null, metadata_json: {} };
const source = { ...installation, id: "source-1234", installation_id: installation.id, connection_type: "desktop_bridge", display_name: "Lucid source", status: "pending", source_namespace: "Lucid connection", source_account_name: "LFE-A", bridge_key_configured: false };

describe("Broker Connections", () => {
  beforeEach(() => { api.mockReset(); api.mockImplementation((path: string) => path === "/broker-connections" ? Promise.resolve([installation, source]) : path === "/imports" ? Promise.resolve([]) : Promise.resolve({})); });

  it("requires an explicit destination before authorizing a discovered source", async () => {
    render(<ConnectionsPage />);
    const authorize = await screen.findByRole("button", { name: "Authorize" });
    expect(authorize).toBeDisabled();
    fireEvent.change(screen.getByLabelText("JournalMe destination for LFE-A"), { target: { value: "journal-1" } });
    fireEvent.click(authorize);
    await waitFor(() => expect(api).toHaveBeenCalledWith("/broker-connections/source-1234/authorize-source", { method: "POST", body: JSON.stringify({ account_id: "journal-1" }) }));
  });

  it("explains preserved history before disconnecting", async () => {
    render(<ConnectionsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Disconnect installation" }));
    expect(screen.getByText(/past trades, screenshots, analyses, and learning data stay in place/)).toBeInTheDocument();
    expect(api).not.toHaveBeenCalledWith("/broker-connections/install-1234/disconnect", expect.anything());
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Disconnect" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/broker-connections/install-1234/disconnect", { method: "POST" }));
  });
});
