import {
  createClient,
  type AuthChangeEvent,
  type Session,
  type SupabaseClient,
} from "@supabase/supabase-js";

export const hostedAuthEnabled =
  process.env.NEXT_PUBLIC_AUTH_MODE === "hosted";

let client: SupabaseClient | undefined;
let accessToken: string | undefined;

function publicSupabaseConfig(): { url: string; key: string } {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key =
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY ??
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !key) {
    throw new Error(
      "Hosted authentication requires NEXT_PUBLIC_SUPABASE_URL and " +
        "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY (or ANON_KEY).",
    );
  }
  return { url, key };
}

export function getSupabaseBrowserClient(): SupabaseClient {
  if (!hostedAuthEnabled) {
    throw new Error("Supabase Auth is disabled in local JournalMe mode.");
  }
  if (!client) {
    const { url, key } = publicSupabaseConfig();
    client = createClient(url, key, {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: true,
        storageKey: "journalme-supabase-auth",
      },
    });
  }
  return client;
}

function rememberSession(session: Session | null): Session | null {
  accessToken = session?.access_token;
  return session;
}

export async function signIn(email: string, password: string): Promise<Session> {
  const { data, error } = await getSupabaseBrowserClient().auth.signInWithPassword({
    email,
    password,
  });
  if (error) throw error;
  if (!data.session) throw new Error("Supabase did not return a user session.");
  return rememberSession(data.session) as Session;
}

export async function signOut(): Promise<void> {
  if (!hostedAuthEnabled) return;
  const { error } = await getSupabaseBrowserClient().auth.signOut({ scope: "local" });
  accessToken = undefined;
  if (error) throw error;
}

export async function getSession(): Promise<Session | null> {
  if (!hostedAuthEnabled) return null;
  const { data, error } = await getSupabaseBrowserClient().auth.getSession();
  if (error) throw error;
  return rememberSession(data.session);
}

export function onAuthStateChange(
  listener: (event: AuthChangeEvent, session: Session | null) => void,
): () => void {
  if (!hostedAuthEnabled) return () => undefined;
  const { data } = getSupabaseBrowserClient().auth.onAuthStateChange(
    (event, session) => {
      rememberSession(session);
      listener(event, session);
    },
  );
  return () => data.subscription.unsubscribe();
}

export async function authorizationHeaders(): Promise<HeadersInit> {
  if (!hostedAuthEnabled) return {};
  if (!accessToken) await getSession();
  return accessToken ? { Authorization: `Bearer ${accessToken}` } : {};
}

export async function invalidateHostedSession(): Promise<void> {
  accessToken = undefined;
  if (!hostedAuthEnabled) return;
  await getSupabaseBrowserClient().auth.signOut({ scope: "local" });
}

/** Test seam; application code should obtain tokens through Supabase sessions. */
export function setHostedAccessToken(token: string | undefined): void {
  accessToken = token;
}
