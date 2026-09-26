"use client";

import { useParams } from "next/navigation";

import { PeriodReview } from "@/components/period-review";

export default function MonthlyReviewPage() {
  const { month } = useParams<{ month: string }>();
  return <PeriodReview kind="monthly" periodStart={month} />;
}
