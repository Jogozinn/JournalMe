"use client";

import { useParams } from "next/navigation";

import { PeriodReview } from "@/components/period-review";

export default function WeeklyReviewPage() {
  const { start } = useParams<{ start: string }>();
  return <PeriodReview kind="weekly" periodStart={start} />;
}
