export type LearningMetrics = {
  trades: number;
  net_pnl: string;
  expectancy: string | null;
  win_rate: string | null;
  average_size: string | null;
};

export type LearningEvidence =
  | "insufficient"
  | "early_signal"
  | "repeated_pattern"
  | "strong_evidence";

export type LearningInsight = {
  key: string;
  title: string;
  evidence: LearningEvidence;
  evidence_score: number;
  explanation: string;
  difference_in_expectancy: string;
  condition: LearningMetrics & { label: string };
  comparison: LearningMetrics & { label: string };
};

export type MindsetInsight = {
  key: string;
  category: string;
  tag: string;
  title: string;
  evidence: LearningEvidence;
  evidence_score: number;
  explanation: string;
  difference_in_average_day_pnl: string;
  tagged: { days: number; average_day_pnl: string; positive_day_rate: string };
  other_reviewed_days: { days: number; average_day_pnl: string; positive_day_rate: string };
};

export type LearningOverview = {
  insights: LearningInsight[];
  mindset_insights: MindsetInsight[];
};

export type ReviewReminderSummary = {
  trades_awaiting_review: number;
  days_awaiting_recap: number;
  review_streak: number;
  completion_percent: number;
};

export type LearningNotice = {
  key: string;
  title: string;
  body: string;
  href: string;
  kind: "pattern" | "mindset" | "review";
};

export const evidenceLabel: Record<LearningEvidence, string> = {
  insufficient: "Insufficient data",
  early_signal: "Early signal",
  repeated_pattern: "Repeated pattern",
  strong_evidence: "Strong evidence",
};

export function buildLearningNotices(
  overview: LearningOverview | null,
  review?: ReviewReminderSummary | null,
): LearningNotice[] {
  const notices: LearningNotice[] = [];
  for (const insight of (overview?.insights ?? []).slice(0, 2)) {
    if (insight.evidence === "insufficient") continue;
    notices.push({
      key: `pattern:${insight.key}:${insight.evidence_score}`,
      title: insight.title,
      body: `${evidenceLabel[insight.evidence]} · ${insight.condition.trades + insight.comparison.trades} trades studied. ${insight.explanation}`,
      href: "/intelligence",
      kind: "pattern",
    });
  }
  const mindset = overview?.mindset_insights?.[0];
  if (mindset && mindset.evidence !== "insufficient") {
    notices.push({
      key: `mindset:${mindset.key}:${mindset.evidence_score}`,
      title: mindset.title,
      body: `${evidenceLabel[mindset.evidence]} · ${mindset.tagged.days + mindset.other_reviewed_days.days} reviewed days. ${mindset.explanation}`,
      href: "/intelligence",
      kind: "mindset",
    });
  }
  if (review && (review.trades_awaiting_review > 0 || review.days_awaiting_recap > 0)) {
    notices.push({
      key: `review:${review.trades_awaiting_review}:${review.days_awaiting_recap}`,
      title: "Your journal has unfinished context",
      body: `${review.trades_awaiting_review} trade${review.trades_awaiting_review === 1 ? "" : "s"} and ${review.days_awaiting_recap} day recap${review.days_awaiting_recap === 1 ? "" : "s"} are waiting.`,
      href: "/review",
      kind: "review",
    });
  }
  return notices.slice(0, 4);
}
