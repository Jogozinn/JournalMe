"use client";

import Link from "next/link";
import { type FormEvent, useState } from "react";

import { BrandMark } from "@/components/brand-mark";
import { useAuth } from "@/components/auth-provider";

export default function ForgotPasswordPage() {
  const { requestPasswordReset } = useAuth();
  const [email, setEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await requestPasswordReset(email.trim().toLowerCase());
      setSent(true);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "JournalMe could not send the reset email.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="login-page auth-page">
      <section className="card login-card auth-card" aria-labelledby="forgot-title">
        <BrandMark />
        <div className="auth-heading">
          <h1 id="forgot-title">Reset your password</h1>
          <p className="muted">Enter your JournalMe email and we will send a secure reset link.</p>
        </div>
        {sent ? (
          <div className="auth-success" role="status">
            <span className="auth-success-mark" aria-hidden="true">✓</span>
            <h2>Check your inbox</h2>
            <p>If an account exists for that address, a password reset link is on its way.</p>
            <Link className="button primary" href="/login">Back to sign in</Link>
          </div>
        ) : (
          <form onSubmit={submit} className="login-form">
            <label>
              Email
              <input
                type="email"
                autoComplete="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
                disabled={submitting}
              />
            </label>
            {error && <p className="form-error" role="alert">{error}</p>}
            <button className="button primary" type="submit" disabled={submitting}>
              {submitting ? "Sending…" : "Send reset link"}
            </button>
          </form>
        )}
        <p className="auth-switch"><Link href="/login">Return to sign in</Link></p>
      </section>
    </main>
  );
}
