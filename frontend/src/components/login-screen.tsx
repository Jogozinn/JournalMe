"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { BrandMark } from "@/components/brand-mark";
import { useAuth } from "@/components/auth-provider";

export function LoginScreen() {
  const router = useRouter();
  const { error: sessionError, signIn } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await signIn(email.trim(), password);
      router.replace("/");
      router.refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "JournalMe could not sign you in.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="login-page auth-page">
      <section className="card login-card auth-card" aria-labelledby="login-title">
        <BrandMark />
        <div className="auth-heading">
          <h1 id="login-title">Welcome back</h1>
          <p className="muted">Sign in to continue to your JournalMe workspace.</p>
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
            <span className="auth-label-row">
              <span>Password</span>
              <Link href="/forgot-password">Forgot password?</Link>
            </span>
            <input
              aria-label="Password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
              disabled={submitting}
            />
          </label>
          {(error || sessionError) && (
            <p className="form-error" role="alert">{error || sessionError}</p>
          )}
          <button className="button primary" type="submit" disabled={submitting}>
            {submitting ? "Signing in…" : "Sign in"}
          </button>
        </form>
        <p className="auth-switch">
          New to JournalMe? <Link href="/register">Create an account</Link>
        </p>
      </section>
    </main>
  );
}
