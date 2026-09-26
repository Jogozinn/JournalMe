import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  vi.clearAllMocks();
  vi.resetModules();
  vi.unstubAllEnvs();
  vi.doUnmock("@supabase/supabase-js");
});

describe("hosted Supabase session boundary", () => {
  it("signs in, restores a session, supplies its bearer token, and signs out", async () => {
    vi.stubEnv("NEXT_PUBLIC_AUTH_MODE", "hosted");
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "https://journalme.supabase.co");
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_ANON_KEY", "publishable-test-key");
    const session = { access_token: "access-token", user: { id: "user-id" } };
    const signInWithPassword = vi.fn().mockResolvedValue({
      data: { session },
      error: null,
    });
    const getSession = vi.fn().mockResolvedValue({
      data: { session },
      error: null,
    });
    const signOut = vi.fn().mockResolvedValue({ error: null });
    const createClient = vi.fn(() => ({
      auth: {
        signInWithPassword,
        getSession,
        signOut,
        onAuthStateChange: vi.fn(() => ({
          data: { subscription: { unsubscribe: vi.fn() } },
        })),
      },
    }));
    vi.doMock("@supabase/supabase-js", () => ({ createClient }));

    const auth = await import("@/lib/auth-session");
    expect(await auth.getSession()).toEqual(session);
    expect(await auth.signIn("trader@example.com", "password")).toEqual(session);
    expect(await auth.authorizationHeaders()).toEqual({
      Authorization: "Bearer access-token",
    });
    expect(signInWithPassword).toHaveBeenCalledWith({
      email: "trader@example.com",
      password: "password",
    });
    expect(createClient).toHaveBeenCalledWith(
      "https://journalme.supabase.co",
      "publishable-test-key",
      expect.objectContaining({
        auth: expect.objectContaining({
          persistSession: true,
          autoRefreshToken: true,
          detectSessionInUrl: true,
          storageKey: "journalme-supabase-auth",
        }),
      }),
    );
    await auth.signOut();
    expect(signOut).toHaveBeenCalledWith({ scope: "local" });
  });

  it("keeps local mode token-free without constructing a Supabase client", async () => {
    vi.stubEnv("NEXT_PUBLIC_AUTH_MODE", "local");
    const createClient = vi.fn();
    vi.doMock("@supabase/supabase-js", () => ({ createClient }));
    const auth = await import("@/lib/auth-session");
    expect(await auth.authorizationHeaders()).toEqual({});
    expect(createClient).not.toHaveBeenCalled();
  });
});
