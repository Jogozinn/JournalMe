"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { BrandMark } from "@/components/brand-mark";
import { useAuth } from "@/components/auth-provider";

export default function RegisterPage() {
  const router = useRouter();
  const { signUp } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmationEmail, setConfirmationEmail] = useState<string | null>(null);

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
      const normalizedEmail = email.trim().toLowerCase();
      const result = await signUp(normalizedEmail, password);
      if (result.session) {
        router.replace("/");
        router.refresh();
        return;
      }
      if (result.needsEmailConfirmation) setConfirmationEmail(normalizedEmail);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "JournalMe could not create your account.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="login-page auth-page">
      <section className="card login-card auth-card" aria-labelledby="register-title">
        <BrandMark />
        {confirmationEmail ? (
          <div className="auth-success" role="status">
            <span className="auth-success-mark" aria-hidden="true">✓</span>
            <h1 id="register-title">Check your email</h1>
            <p>
              We sent a confirmation link to <strong>{confirmationEmail}</strong>. Open it to finish creating your JournalMe account.
            </p>
            <Link className="button primary" href="/login">Back to sign in</Link>
          </div>
        ) : (
          <>
            <div className="auth-heading">
              <h1 id="register-title">Create your JournalMe account</h1>
              <p className="muted">Your journal, screenshots, accounts, and reviews stay attached to your sign-in.</p>
            </div>
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
              <label>
                Password
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
                Confirm password
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
                {submitting ? "Creating account…" : "Create account"}
              </button>
            </form>
            <p className="auth-switch">Already have an account? <Link href="/login">Sign in</Link></p>
          </>
        )}
      </section>
    </main>
  );
}
