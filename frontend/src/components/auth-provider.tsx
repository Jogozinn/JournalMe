"use client";

import type { Session } from "@supabase/supabase-js";
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import {
  getSession,
  hostedAuthEnabled,
  onAuthStateChange,
  requestPasswordReset as requestPasswordResetSession,
  signIn as signInSession,
  signOut as signOutSession,
  signUp as signUpSession,
  updatePassword as updatePasswordSession,
} from "@/lib/auth-session";

type SignUpResult = {
  session: Session | null;
  needsEmailConfirmation: boolean;
};

type AuthContextValue = {
  hosted: boolean;
  loading: boolean;
  session: Session | null;
  error: string | null;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string) => Promise<SignUpResult>;
  requestPasswordReset: (email: string) => Promise<void>;
  updatePassword: (password: string) => Promise<void>;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(hostedAuthEnabled);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!hostedAuthEnabled) return;
    let active = true;
    const unsubscribe = onAuthStateChange((_, nextSession) => {
      if (!active) return;
      setSession(nextSession);
      setLoading(false);
    });
    void getSession()
      .then((nextSession) => {
        if (active) setSession(nextSession);
      })
      .catch((cause: unknown) => {
        if (active) {
          setError(cause instanceof Error ? cause.message : "Session restoration failed.");
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      unsubscribe();
    };
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      hosted: hostedAuthEnabled,
      loading,
      session,
      error,
      signIn: async (email, password) => {
        setError(null);
        const nextSession = await signInSession(email, password);
        setSession(nextSession);
      },
      signUp: async (email, password) => {
        setError(null);
        const result = await signUpSession(email, password);
        if (result.session) setSession(result.session);
        return result;
      },
      requestPasswordReset: async (email) => {
        setError(null);
        await requestPasswordResetSession(email);
      },
      updatePassword: async (password) => {
        setError(null);
        await updatePasswordSession(password);
      },
      signOut: async () => {
        setError(null);
        await signOutSession();
        setSession(null);
      },
    }),
    [error, loading, session],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider.");
  return value;
}
