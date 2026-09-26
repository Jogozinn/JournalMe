import { describe, expect, it } from "vitest";

import {
  applicable,
  cleanDecimalInput,
  optionalFormValue,
  scalingTiersFromForm,
} from "./prop";

describe("prop form normalization", () => {
  it("turns blank and whitespace-only optional values into null", () => {
    const form = new FormData();
    form.set("blank", "");
    form.set("spaces", "   ");
    expect(optionalFormValue(form, "blank")).toBeNull();
    expect(optionalFormValue(form, "spaces")).toBeNull();
  });

  it("preserves explicit numeric zero", () => {
    const form = new FormData();
    form.set("value", "0");
    expect(optionalFormValue(form, "value")).toBe("0");
  });

  it("renders missing rules as Not applicable and cleans Decimal inputs", () => {
    expect(applicable(null, String)).toBe("Not applicable");
    expect(applicable("0", (value) => `${value}%`)).toBe("0%");
    expect(cleanDecimalInput("50000.0000")).toBe("50000");
  });

  it("normalizes blank scaling upper bounds", () => {
    const form = new FormData();
    form.append("tier_lower", "0");
    form.append("tier_upper", " ");
    form.append("tier_minis", "2");
    form.append("tier_micros", "20");
    expect(scalingTiersFromForm(form)).toEqual([
      {
        lower_profit_bound: "0",
        upper_profit_bound: null,
        max_mini_contracts: 2,
        max_micro_contracts: 20,
      },
    ]);
  });
});
