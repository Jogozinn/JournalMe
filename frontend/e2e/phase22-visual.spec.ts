import path from "node:path";

import { expect, test } from "@playwright/test";

const runVisual = process.env.JOURNALME_PHASE22_E2E === "1";
const flexId = "c777b1ea-e964-4860-8df3-68f5da57d534";
const dailyId = "f1f3dd0c-4932-4da1-85a8-889a5e459dec";

test.describe("Phase 2.2 balance and preset visuals", () => {
  test.skip(!runVisual, "Set JOURNALME_PHASE22_E2E=1 against the isolated production stack.");

  test("captures balance, presets, required configuration, and funded tracker", async ({ page }, testInfo) => {
    const mode = testInfo.project.name.includes("mobile") ? "mobile" : "desktop";
    const output = (name: string) =>
      path.join("artifacts", "phase22", `${mode}-${name}.png`);
    await page.addInitScript((id) => {
      window.localStorage.setItem("journalme-account", id);
    }, flexId);

    await page.goto("/");
    await expect(page.getByText("$51,748.25", { exact: true })).toBeVisible();
    await page.screenshot({ path: output("home-corrected-balance"), fullPage: true });

    await page.goto(`/accounts/${flexId}`);
    await expect(page.getByText("LucidFlex", { exact: true })).toBeVisible();
    await expect(page.getByText("$51,748.25", { exact: true }).first()).toBeVisible();
    await page.screenshot({ path: output("lucidflex-detail"), fullPage: true });

    await page.goto("/accounts");
    await page.getByRole("button", { name: "Create from preset" }).click();
    await expect(page.getByRole("heading", { name: "Step 1 of 6" })).toBeVisible();
    await page.screenshot({ path: output("preset-selector"), fullPage: true });

    await page.goto(`/accounts/${dailyId}`);
    await expect(page.getByText("Configuration required.", { exact: false })).toBeVisible();
    await page.screenshot({ path: output("daily-evaluation-required"), fullPage: true });

    await page.goto("/accounts");
    await page.getByRole("button", { name: "Create from preset" }).click();
    await page.getByLabel("Plan family").selectOption("LucidDaily");
    await page.getByRole("button", { name: "Continue" }).click();
    await page.getByLabel("Phase").selectOption("Evaluation");
    await page.getByRole("button", { name: "Continue" }).click();
    await page.getByRole("button", { name: "Continue" }).click();
    await page.getByLabel("End-of-Day trailing").check();
    await page.getByLabel("ON · fixed $1,200").check();
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page.getByText("LucidDaily Evaluation 50K", { exact: true })).toBeVisible();
    await page.screenshot({ path: output("daily-evaluation-configured"), fullPage: true });

    const fundedId = "phase22-funded-preview";
    const accountPayload = {
      id: fundedId,
      name: "Lucid Daily Funded 50K Preview",
      external_account_id: null,
      provider: "tradovate",
      account_type: "funded",
      starting_balance: "50000.00",
      current_balance: "53000.00",
      timezone: "America/New_York",
      currency: "USD",
      active: true,
      notes: null,
      configuration_required: false,
      active_plan: {
        preset_key: "lucid_daily_funded_50k",
        plan_family: "LucidDaily",
        phase: "Funded",
        account_size: "50000.00",
      },
      balance_resolution: {
        starting_balance: "50000.00",
        imported_balance: null,
        imported_balance_as_of: null,
        calculated_balance: "53000.00",
        calculated_balance_as_of: "2026-07-30T20:00:00+00:00",
        resolved_current_balance: "53000.00",
        resolution_method: "calculated_from_ledger",
        reconciliation_difference: null,
        stale_snapshot: false,
      },
    };
    await page.route(`**/api/v1/accounts/${fundedId}`, (route) =>
      route.fulfill({ json: accountPayload }),
    );
    await page.route(`**/api/v1/prop-rules/${fundedId}/status`, (route) =>
      route.fulfill({
        json: {
          verified: {},
          status: {
            current_balance: "53000.00",
            net_profit: "3000.00",
            profit_remaining: null,
            best_day_percent: null,
            additional_profit_for_consistency: null,
            maximum_loss_buffer: "5000.00",
            daily_loss_buffer: null,
            minimum_days_remaining: null,
            estimated_pass: true,
            maximum_loss_floor: "48000.00",
            high_water_balance: "53000.00",
          },
          configured: {
            profit_target: null,
            daily_loss_limit: null,
            consistency_percent: null,
            payout_buffer: null,
            minimum_profit_per_qualifying_day: null,
            payout_buffer_balance_threshold: "52100.00",
            max_daily_simulated_profit: "8000.00",
            news_restriction_note: "Red-folder news trading is prohibited. Remain flat from one minute before through one minute after the event.",
            live_transition_note: "$8,000 is a firm live-review condition; JournalMe cannot transition the account.",
          },
          payout_cycle: {
            start_date: "2026-07-30",
            cycle_net_profit: "3000.00",
            qualifying_day_count: 0,
            qualifying_day_required: null,
            qualifying_day_dates: [],
            eligible_for_payout: true,
            gross_available_payout: "900.00",
            minimum_payout_met: true,
            requestable_payout: "900.00",
            estimated_trader_share: "810.00",
            estimated_firm_share: "90.00",
            payouts_completed: 0,
            maximum_payout_count: null,
            ineligibility_reasons: [],
          },
          scaling: {
            current: {
              lower_profit_bound: "0.00",
              upper_profit_bound: null,
              max_mini_contracts: 4,
              max_micro_contracts: 40,
            },
            previous: null,
            next: null,
          },
          profile_version: {
            version_number: 1,
            effective_date: "2026-07-30",
            source_note: "Preview of the versioned catalog values.",
          },
          formulas: {},
          warning: "Informational estimate. Verify every configured rule against the firm agreement.",
        },
      }),
    );
    await page.route(`**/api/v1/prop-rules/${fundedId}/payouts`, (route) =>
      route.fulfill({ json: [] }),
    );
    await page.route(`**/api/v1/manual-adjustments?account_id=${fundedId}`, (route) =>
      route.fulfill({ json: [] }),
    );
    await page.route(`**/api/v1/prop-rules/${fundedId}`, (route) =>
      route.fulfill({
        json: {
          id: "preview-profile",
          firm_name: "Lucid Trading",
          account_label: "LucidDaily Funded 50K",
          profile_account_type: "LucidDaily Funded",
          starting_balance: "50000.00",
          profit_target: null,
          max_loss: "2000.00",
          daily_loss_limit: null,
          consistency_percent: null,
          drawdown_type: "intraday_trailing",
          drawdown_amount: "2000.00",
          minimum_trading_days: null,
          payout_buffer: null,
          enabled: true,
          qualifying_profit_days_required: null,
          minimum_profit_per_qualifying_day: null,
          payout_cycle_net_profit_required: true,
          minimum_payout: "500.00",
          payout_profit_percentage: null,
          maximum_payout: null,
          maximum_payout_count: null,
          profit_split_trader_percent: "90.00",
          profit_split_firm_percent: "10.00",
          no_fixed_payout_window: true,
          payout_cycle_start_date: "2026-07-30",
          qualifying_days_since_last_payout: 0,
          payouts_completed: 0,
          preset_key: "lucid_daily_funded_50k",
          effective_date: "2026-07-30",
          source_note: "Preview",
          scaling_tiers: [{
            lower_profit_bound: "0.00",
            upper_profit_bound: null,
            max_mini_contracts: 4,
            max_micro_contracts: 40,
          }],
          version: { version_number: 1, effective_date: "2026-07-30" },
          configuration_state: "configured",
          evaluation_drawdown_choice: null,
          daily_loss_limit_enabled: false,
          daily_loss_limit_amount: null,
          initial_trail_balance: "52100.00",
          locked_mll_balance: "50100.00",
          payout_buffer_balance_threshold: "52100.00",
          max_daily_simulated_profit: "8000.00",
          news_restriction_note: "Red-folder restriction",
          live_transition_note: "$8,000 review threshold",
          purchase_configuration: {},
        },
      }),
    );
    await page.route("**/api/v1/accounts", async (route) => {
      const response = await route.fetch();
      const accounts = await response.json();
      await route.fulfill({
        response,
        json: [...accounts, accountPayload],
      });
    });
    await page.goto(`/accounts/${fundedId}`);
    await expect(page.getByText("LucidDaily", { exact: true })).toBeVisible();
    await expect(page.getByText("$52,100.00", { exact: true }).first()).toBeVisible();
    await page.screenshot({ path: output("daily-funded-tracker"), fullPage: true });
  });
});
