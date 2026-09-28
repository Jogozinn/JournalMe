import { afterEach, describe, expect, it, vi } from "vitest";

import { api, duration, errorMessage, hourLabel12, money, percent, quantity, timeOnly } from "@/lib/api";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("financial presentation", () => {
  it("distinguishes unavailable values from zero", () => {
    expect(money(null)).toBe("Unavailable");
    expect(money("0")).toContain("$0.00");
    expect(percent(null)).toBe("Unavailable");
    expect(percent("0")).toBe("0.0%");
  });

  it("formats imported durations", () => {
    expect(duration(4636)).toBe("1h 17m 16s");
    expect(duration(null)).toBe("Unavailable");
  });

  it("removes broker precision noise while preserving fractional quantities", () => {
    expect(quantity("1.000000", true)).toBe("1 contract");
    expect(quantity("4.000000", true)).toBe("4 contracts");
    expect(quantity("1.25", true)).toBe("1.25 contracts");
    expect(quantity(null)).toBe("Unavailable");
  });

  it("uses 12-hour labels for trading times", () => {
    expect(hourLabel12("00:00")).toBe("12:00 AM");
    expect(hourLabel12("13:00")).toBe("1:00 PM");
    expect(timeOnly(new Date(2026, 8, 28, 21, 5))).toContain("9:05 PM");
  });
});

describe("structured import errors", () => {
  it("keeps validation errors field-specific", () => {
    expect(
      errorMessage([
        {
          loc: ["body", "profit_target"],
          msg: "Input should be a valid decimal.",
        },
      ]),
    ).toBe("profit target: Input should be a valid decimal.");
  });

  it("shows report, row, column, field, and reason", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: {
            message: "1 required import value failed validation.",
            errors: [
              {
                report_type: "cash_history",
                filename: "Cash History.csv",
                row_number: 2,
                source_column: "Amount",
                field_name: "amount",
                reason: "is required but blank or unavailable.",
              },
            ],
          },
        }),
        {
          status: 422,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );

    await expect(api("/imports/session/commit", { method: "POST" })).rejects.toThrow(
      "Cash History.csv, CSV row 2, column Amount (amount): " +
        "is required but blank or unavailable.",
    );
  });
});

describe("request stabilization", () => {
  it("deduplicates concurrent GET requests for the same resource", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify([{ id: "one" }]), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    const [first, second] = await Promise.all([
      api<{ id: string }[]>("/accounts"),
      api<{ id: string }[]>("/accounts"),
    ]);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(first).toEqual(second);
  });
});
