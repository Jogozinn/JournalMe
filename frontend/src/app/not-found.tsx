import Link from "next/link";

import { BrandMark } from "@/components/brand-mark";

export default function NotFound() {
  return (
    <main className="not-found-page">
      <section className="not-found-card">
        <BrandMark />
        <div className="not-found-code" aria-hidden="true">404</div>
        <h1>This page is not in your journal.</h1>
        <p>The link may be old, incomplete, or pointing to something that moved.</p>
        <div className="not-found-actions">
          <Link className="button primary" href="/">Go home</Link>
          <Link className="button" href="/trades">Open trades</Link>
        </div>
      </section>
    </main>
  );
}
