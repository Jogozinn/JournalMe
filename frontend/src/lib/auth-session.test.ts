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
    const signUp = vi.fn().mockResolvedValue({
      data: { session: null, user: { id: "new-user" } },
      error: null,
    });
    const resetPasswordForEmail = vi.fn().mockResolvedValue({ error: null });
    const updateUser = vi.fn().mockResolvedValue({ data: { user: {} }, error: null });
    const signOut = vi.fn().mockResolvedValue({ error: null });
    const refreshSession = vi.fn().mockResolvedValue({
      data: { session: { ...session, access_token: "refreshed-token" } },
      error: null,
    });
    const createClient = vi.fn(() => ({
      auth: {
        signInWithPassword,
        signUp,
        resetPasswordForEmail,
        updateUser,
        getSession,
        refreshSession,
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
    expect(await auth.refreshAuthorizationHeaders()).toEqual({
      Authorization: "Bearer refreshed-token",
    });
    expect(refreshSession).toHaveBeenCalledOnce();
    expect(signInWithPassword).toHaveBeenCalledWith({
      email: "trader@example.com",
      password: "password",
    });
    expect(await auth.signUp("new@example.com", "password123")).toEqual({
      session: null,
      needsEmailConfirmation: true,
    });
    await auth.requestPasswordReset("trader@example.com");
    await auth.updatePassword("new-password");
    expect(signUp).toHaveBeenCalledWith({
      email: "new@example.com",
      password: "password123",
    });
    expect(resetPasswordForEmail).toHaveBeenCalledWith(
      "trader@example.com",
      expect.objectContaining({ redirectTo: expect.stringContaining("/reset-password") }),
    );
    expect(updateUser).toHaveBeenCalledWith({ password: "new-password" });
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
