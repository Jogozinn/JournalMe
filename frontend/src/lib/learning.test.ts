import { describe, expect, it } from "vitest";

import { buildLearningNotices, type LearningOverview } from "@/lib/learning";

const overview: LearningOverview = {
  insights: [
    {
      key: "after_loss",
      title: "Your next trade after a loss is weaker",
      evidence: "strong_evidence",
      evidence_score: 90,
      explanation: "The relationship repeats across comparable accounts.",
      difference_in_expectancy: "-40",
      condition: { label: "After a loss", trades: 12, net_pnl: "-120", expectancy: "-10", win_rate: "40", average_size: "2" },
      comparison: { label: "Otherwise", trades: 20, net_pnl: "600", expectancy: "30", win_rate: "60", average_size: "2" },
    },
  ],
  mindset_insights: [],
};

describe("learning notices", () => {
  it("surfaces evidence-backed patterns with their sample size", () => {
    const notices = buildLearningNotices(overview, null);
    expect(notices[0].title).toContain("after a loss");
    expect(notices[0].body).toContain("32 trades studied");
    expect(notices[0].href).toBe("/intelligence");
  });

  it("can add a review reminder without inventing coaching", () => {
    const notices = buildLearningNotices(overview, {
      trades_awaiting_review: 3,
      days_awaiting_recap: 1,
      review_streak: 0,
      completion_percent: 50,
    });
    expect(notices.some((item) => item.kind === "review")).toBe(true);
  });
});
