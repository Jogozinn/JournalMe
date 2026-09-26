import { expect, test } from "@playwright/test";

const account = {
  id: "00000000-0000-0000-0000-000000000001",
  name: "Practice account",
  external_account_id: "MASKED-0001",
  provider: "tradovate",
  account_type: "simulated",
  starting_balance: "50000",
  timezone: "America/New_York",
  currency: "USD",
  active: true,
};

test.beforeEach(async ({ page }) => {
  await page.route("**/api/v1/accounts", (route) =>
    route.fulfill({ json: [account] }),
  );
  await page.route("**/api/v1/imports/preview*", (route) =>
    route.fulfill({
      status: 201,
      json: {
        session_id: "00000000-0000-0000-0000-000000000099",
        status: "ready",
        reports: [
          {
            filename: "Performance (1).csv",
            type: "performance",
            rows: 13,
            duplicate_rows: 1,
            status: "recognized",
          },
          {
            filename: "Order Details.csv",
            type: "order_details_empty",
            rows: 0,
            duplicate_rows: 0,
            status: "skipped",
          },
        ],
        coverage: { start: "2026-07-27", end: "2026-07-29" },
        detected_accounts: ["MASKED-0001"],
        canonical_trades: 12,
        new_trades: 12,
        existing_trades: 0,
        duplicate_rows: 1,
        unmatched_fills: 0,
        linked_filled_orders: 24,
        canceled_unfilled_orders: 13,
        unmatched_filled_orders: 0,
        unmatched_orders: 0,
        warnings: ["Empty Order Details report was skipped."],
        errors: [],
      },
    }),
  );
  await page.route("**/api/v1/imports/*/commit", (route) =>
    route.fulfill({
      json: {
        status: "committed",
        created: { trades: 12, fills: 25, orders: 37 },
      },
    }),
  );
  await page.route("**/api/v1/trades?*", (route) =>
    route.fulfill({ json: { items: [], total: 0, page: 1 } }),
  );
});

test("previews and commits a multi-report import", async ({ page }, testInfo) => {
  await page.goto("/import");
  await page.locator('input[type="file"]').setInputFiles([
    {
      name: "Performance (1).csv",
      mimeType: "text/csv",
      buffer: Buffer.from(
        "symbol,buyFillId,sellFillId,qty,pnl,boughtTimestamp,soldTimestamp,duration\n",
      ),
    },
    {
      name: "Order Details.csv",
      mimeType: "text/csv",
      buffer: Buffer.from("undefined\n"),
    },
  ]);
  await page.getByRole("button", { name: "Review import" }).click();
  await expect(page.getByText("12 new canonical trades")).toBeVisible();
  await expect(page.getByText("13 rows")).toBeVisible();
  await expect(page.getByText("Canceled/unfilled retained")).toBeVisible();
  await expect(
    page.getByText("Unmatched filled orders"),
  ).toBeVisible();
  await expect(page.getByText("Empty Order Details report was skipped.")).toBeVisible();
  if (testInfo.project.name === "mobile-safari") {
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({
      path: "artifacts/import-preview-mobile.png",
      fullPage: false,
    });
  }
  await page.getByRole("button", { name: "Confirm atomic import" }).click();
  await expect(page).toHaveURL(/\/trades$/);
});

test("mobile shell avoids horizontal page overflow", async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.includes("mobile"));
  await page.goto("/import");
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(overflow).toBe(false);
  await expect(page.getByLabel("Mobile navigation")).toBeVisible();
});
