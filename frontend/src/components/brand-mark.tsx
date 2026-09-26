import { brand } from "@/config/brand";

export function BrandMark({ compact = false }: { compact?: boolean }) {
  return (
    <div className="brand-mark" aria-label={brand.name}>
      <svg viewBox="0 0 42 42" role="img" aria-hidden="true">
        <path d="M9 8.5h16.5A7.5 7.5 0 0 1 33 16v17.5H16.5A7.5 7.5 0 0 1 9 26V8.5Z" />
        <path d="m14 25 4.5-5 4 3 5.5-8" className="brand-chart" />
        <path d="M14 31h13" className="brand-line" />
      </svg>
      {!compact && (
        <span>
          Journal<span>Me</span>
        </span>
      )}
    </div>
  );
}

