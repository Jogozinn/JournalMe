"use client";

import { useEffect, useMemo, useState } from "react";

import { useAccount } from "@/components/account-provider";
import { useAuth } from "@/components/auth-provider";
import { ErrorState, PageHeader } from "@/components/ui";
import { API_BASE_URL } from "@/lib/api";

const extensionIdPattern = /^[a-p]{32}$/;

type ExternalMessageResponse = { ok?: boolean; error?: string } | undefined;
type ExternalChrome = {
  runtime?: {
    lastError?: { message?: string };
    sendMessage: (
      extensionId: string,
      message: unknown,
      callback: (response: ExternalMessageResponse) => void,
    ) => void;
  };
};

function apiRoot(): string {
  return API_BASE_URL.endsWith("/api/v1")
    ? API_BASE_URL.slice(0, -"/api/v1".length)
    : API_BASE_URL;
}

export default function CompanionConnectPage() {
  const { hosted, session } = useAuth();
  const { account } = useAccount();
  const [extensionId, setExtensionId] = useState("");
  const [nonce, setNonce] = useState("");
  const [connecting, setConnecting] = useState(false);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setExtensionId(params.get("extension_id") || "");
    setNonce(params.get("nonce") || "");
  }, []);

  const validRequest = useMemo(
    () => extensionIdPattern.test(extensionId) && nonce.length >= 16,
    [extensionId, nonce],
  );

  async function connect() {
    setError("");
    if (!hosted) {
      setError("Companion cloud connection is only needed in hosted JournalMe mode.");
      return;
    }
    if (!session) {
      setError("Sign in to JournalMe before connecting the Companion.");
      return;
    }
    if (!validRequest) {
      setError("This Companion connection request is invalid. Open it again from the extension.");
      return;
    }
    const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
    const supabaseAnonKey =
      process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY ??
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
    if (!supabaseUrl || !supabaseAnonKey || !session.refresh_token) {
      setError("JournalMe is missing the browser-safe hosted auth configuration needed by Companion.");
      return;
    }

    const chromeApi = (window as typeof window & { chrome?: ExternalChrome }).chrome;
    if (!chromeApi?.runtime?.sendMessage) {
      setError("Chrome could not reach JournalMe Companion. Confirm the extension is loaded and try again.");
      return;
    }

    setConnecting(true);
    const response = await new Promise<ExternalMessageResponse>((resolve) => {
      chromeApi.runtime?.sendMessage(
        extensionId,
        {
          type: "JOURNALME_COMPANION_CONNECT",
          nonce,
          accessToken: session.access_token,
          refreshToken: session.refresh_token,
          expiresAt: session.expires_at ?? 0,
          userEmail: session.user.email ?? null,
          accountId: account?.id ?? null,
          supabaseUrl,
          supabaseAnonKey,
          apiBase: apiRoot(),
          appBase: window.location.origin,
        },
        (result) => {
          const runtimeError = chromeApi.runtime?.lastError?.message;
          resolve(runtimeError ? { ok: false, error: runtimeError } : result);
        },
      );
    });
    setConnecting(false);
    if (!response?.ok) {
      setError(response?.error || "JournalMe Companion did not accept the connection.");
      return;
    }
    setConnected(true);
  }

  return (
    <>
      <PageHeader
        title="Connect Companion"
        description="Link the Chrome sidebar to this JournalMe account so captures save to the same cloud journal you see here."
      />
      <section className="companion-connect-card card">
        <div className={`companion-connect-mark ${connected ? "connected" : ""}`} aria-hidden="true" />
        <div>
          <h2>{connected ? "Companion connected" : "Ready to connect"}</h2>
          <p>
            {connected
              ? "Your Chrome captures can now save directly to this JournalMe account."
              : "The extension opened this page with a one-time connection request. JournalMe will only share this session after you approve it here."}
          </p>
        </div>
        {!connected && (
          <button
            className="button primary"
            type="button"
            disabled={connecting || !validRequest || !session}
            onClick={() => void connect()}
          >
            {connecting ? "Connecting..." : "Connect Companion"}
          </button>
        )}
        {connected && <a className="button primary" href="/captures">Open captures</a>}
      </section>
      {error && <ErrorState message={error} />}
      {!session && hosted && (
        <p className="muted companion-connect-note">Sign in first, then reopen Connect web from the Companion sidebar.</p>
      )}
    </>
  );
}
