import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  vi.restoreAllMocks();
  vi.resetModules();
  vi.doUnmock("@/lib/auth-session");
});

describe("authenticated JournalMe API", () => {
  it("adds the current bearer token to cloud API requests", async () => {
    vi.doMock("@/lib/auth-session", () => ({
      authorizationHeaders: vi.fn().mockResolvedValue({
        Authorization: "Bearer cloud-access-token",
      }),
      hostedAuthEnabled: true,
      refreshAuthorizationHeaders: vi.fn(),
    }));
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify([{ id: "account" }]), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const { api } = await import("@/lib/api");
    await api("/accounts");
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/accounts"),
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer cloud-access-token",
        }),
      }),
    );
  });

  it("refreshes once and retries after an unauthorized API response", async () => {
    const refreshAuthorizationHeaders = vi.fn().mockResolvedValue({
      Authorization: "Bearer refreshed-token",
    });
    vi.doMock("@/lib/auth-session", () => ({
      authorizationHeaders: vi.fn().mockResolvedValue({
        Authorization: "Bearer expired-token",
      }),
      hostedAuthEnabled: true,
      refreshAuthorizationHeaders,
    }));
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "Authentication is required." }), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify([{ id: "trade" }]), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    const { api } = await import("@/lib/api");
    await expect(api("/trades")).resolves.toEqual([{ id: "trade" }]);
    expect(refreshAuthorizationHeaders).toHaveBeenCalledOnce();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1]?.[1]).toEqual(
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer refreshed-token",
        }),
      }),
    );
  });

  it("does not force a Supabase logout when the refreshed API request is still unauthorized", async () => {
    const refreshAuthorizationHeaders = vi.fn().mockResolvedValue({
      Authorization: "Bearer refreshed-token",
    });
    vi.doMock("@/lib/auth-session", () => ({
      authorizationHeaders: vi.fn().mockResolvedValue({
        Authorization: "Bearer expired-token",
      }),
      hostedAuthEnabled: true,
      refreshAuthorizationHeaders,
    }));
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Authentication is required." }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const { api } = await import("@/lib/api");
    await expect(api("/trades")).rejects.toMatchObject({ status: 401 });
    expect(refreshAuthorizationHeaders).toHaveBeenCalledOnce();
  });
});
