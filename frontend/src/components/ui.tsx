import Link from "next/link";

import { Icon } from "@/components/icons";

export function PageHeader({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <header className="page-header">
      <div>
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {action}
    </header>
  );
}

export function EmptyState({
  title,
  copy,
  href = "/import",
  action = "Import trading data",
}: {
  title: string;
  copy: string;
  href?: string;
  action?: string;
}) {
  return (
    <section className="empty-state card">
      <div className="empty-icon">
        <Icon name="journal" />
      </div>
      <h2>{title}</h2>
      <p>{copy}</p>
      <Link className="button primary" href={href}>
        {action}
      </Link>
    </section>
  );
}

export function Pnl({
  value,
  children,
}: {
  value: string | number | null;
  children: React.ReactNode;
}) {
  const number = value === null ? null : Number(value);
  const className =
    number === null ? "muted" : number > 0 ? "positive" : number < 0 ? "negative" : "";
  return <span className={className}>{children}</span>;
}

export function Skeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="skeleton card" aria-label="Loading">
      {Array.from({ length: rows }).map((_, index) => (
        <span key={index} />
      ))}
    </div>
  );
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="notice error" role="alert">
      {message}
    </div>
  );
}

