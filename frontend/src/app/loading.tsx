import { Skeleton } from "@/components/ui";

export default function Loading() {
  return (
    <section aria-label="Loading page" aria-live="polite">
      <Skeleton rows={6} />
    </section>
  );
}
