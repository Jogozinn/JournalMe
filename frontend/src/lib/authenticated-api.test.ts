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
      invalidateHostedSession: vi.fn(),
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

  it("invalidates the hosted session after an unauthorized API response", async () => {
    const invalidateHostedSession = vi.fn().mockResolvedValue(undefined);
    vi.doMock("@/lib/auth-session", () => ({
      authorizationHeaders: vi.fn().mockResolvedValue({
        Authorization: "Bearer expired-token",
      }),
      hostedAuthEnabled: true,
      invalidateHostedSession,
    }));
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Authentication is required." }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const { api } = await import("@/lib/api");
    await expect(api("/trades")).rejects.toMatchObject({ status: 401 });
    expect(invalidateHostedSession).toHaveBeenCalledOnce();
  });
});
