"use client";

import Link from "next/link";
import { type FormEvent, useEffect, useState } from "react";

import { BrandMark } from "@/components/brand-mark";
import { useAuth } from "@/components/auth-provider";
import { getSession } from "@/lib/auth-session";

export default function ResetPasswordPage() {
  const { session, updatePassword } = useAuth();
  const [ready, setReady] = useState(Boolean(session));
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (session) {
      setReady(true);
      return;
    }
    let active = true;
    void getSession()
      .then((nextSession) => {
        if (active) setReady(Boolean(nextSession));
      })
      .catch(() => {
        if (active) setReady(false);
      });
    return () => {
      active = false;
    };
  }, [session]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    if (password.length < 8) {
      setError("Use at least 8 characters for your password.");
      return;
    }
    if (password !== confirmPassword) {
      setError("The passwords do not match.");
      return;
    }
    setSubmitting(true);
    try {
      await updatePassword(password);
      setSaved(true);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "JournalMe could not update your password.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="login-page auth-page">
      <section className="card login-card auth-card" aria-labelledby="reset-title">
        <BrandMark />
        {saved ? (
          <div className="auth-success" role="status">
            <span className="auth-success-mark" aria-hidden="true">✓</span>
            <h1 id="reset-title">Password updated</h1>
            <p>Your new password is ready. You can continue to JournalMe.</p>
            <Link className="button primary" href="/">Open JournalMe</Link>
          </div>
        ) : ready ? (
          <>
            <div className="auth-heading">
              <h1 id="reset-title">Choose a new password</h1>
              <p className="muted">Use a password you do not reuse elsewhere.</p>
            </div>
            <form onSubmit={submit} className="login-form">
              <label>
                New password
                <input
                  type="password"
                  autoComplete="new-password"
                  minLength={8}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  required
                  disabled={submitting}
                />
              </label>
              <label>
                Confirm new password
                <input
                  type="password"
                  autoComplete="new-password"
                  minLength={8}
                  value={confirmPassword}
                  onChange={(event) => setConfirmPassword(event.target.value)}
                  required
                  disabled={submitting}
                />
              </label>
              {error && <p className="form-error" role="alert">{error}</p>}
              <button className="button primary" type="submit" disabled={submitting}>
                {submitting ? "Updating…" : "Update password"}
              </button>
            </form>
          </>
        ) : (
          <div className="auth-success auth-expired" role="alert">
            <h1 id="reset-title">This reset link is no longer active</h1>
            <p>Request a new password reset link and use the newest email from JournalMe.</p>
            <Link className="button primary" href="/forgot-password">Request a new link</Link>
          </div>
        )}
      </section>
    </main>
  );
}
