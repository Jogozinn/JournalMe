export type ScalingTierInput = {
  lower_profit_bound: string;
  upper_profit_bound: string | null;
  max_mini_contracts: number;
  max_micro_contracts: number;
};

export function optionalFormValue(
  form: FormData,
  name: string,
): string | null {
  const value = form.get(name);
  if (value === null) return null;
  const normalized = String(value).trim();
  return normalized === "" ? null : normalized;
}

export function applicable<T>(
  value: T | null | undefined,
  format: (present: T) => string,
): string {
  return value === null || value === undefined
    ? "Not applicable"
    : format(value);
}

export function cleanDecimalInput(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "";
  return value.includes(".")
    ? value.replace(/\.?0+$/, "")
    : value;
}

export function scalingTiersFromForm(form: FormData): ScalingTierInput[] {
  const lowers = form.getAll("tier_lower");
  const uppers = form.getAll("tier_upper");
  const minis = form.getAll("tier_minis");
  const micros = form.getAll("tier_micros");
  return lowers
    .map((lower, index) => ({
      lower_profit_bound: String(lower).trim(),
      upper_profit_bound:
        String(uppers[index] ?? "").trim() === ""
          ? null
          : String(uppers[index]).trim(),
      max_mini_contracts: Number(minis[index]),
      max_micro_contracts: Number(micros[index]),
    }))
    .filter((item) => item.lower_profit_bound !== "");
}
