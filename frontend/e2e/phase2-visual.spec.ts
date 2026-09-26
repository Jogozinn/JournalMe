import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

const output = path.resolve(process.cwd(), "artifacts", "phase2");

async function capture(page: Page, name: string) {
  await page.screenshot({
    path: path.join(output, name),
    fullPage: true,
  });
}

test.beforeEach(({}, testInfo) => {
  test.skip(
    process.env.JOURNALME_REAL_E2E !== "1",
    "Runs only against explicitly started local API and frontend processes.",
  );
  testInfo.setTimeout(120_000);
});

test("Phase 2 desktop real-data workflows render", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "Desktop visual acceptance.");

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Welcome back." })).toBeVisible();
  await expect(page.getByText("$52,121.70")).toBeVisible();
  await expect(page.getByText("$2,121.70").first()).toBeVisible();
  await capture(page, "desktop-home.png");

  await page.goto("/timeline/2026-07-29");
  await expect(page.getByRole("heading", { name: /July 29, 2026/ })).toBeVisible();
  await expect(page.getByText("10 trades").first()).toBeVisible();
  await capture(page, "desktop-trading-day.png");

  await page.goto("/trades");
  await expect(page.getByText("12 normalized trades")).toBeVisible();
  await capture(page, "desktop-trades.png");
  await page.locator('.trade-table a[href^="/trades/"]').first().click();
  await expect(page.getByRole("heading", { name: /· (long|short)/i })).toBeVisible();
  await capture(page, "desktop-trade-review.png");

  await page.goto("/calendar");
  await expect(page.getByRole("heading", { name: "Calendar" })).toBeVisible();
  await capture(page, "desktop-calendar-month.png");
  await page.getByRole("button", { name: "week" }).click();
  await capture(page, "desktop-calendar-week.png");

  await page.goto("/analytics");
  await expect(page.getByRole("heading", { name: "Analytics" })).toBeVisible();
  await capture(page, "desktop-analytics.png");

  await page.goto("/playbooks");
  await expect(page.getByRole("heading", { name: "Playbooks" })).toBeVisible();
  await page.locator('a[href^="/playbooks/"]').first().click();
  await expect(page.getByText("Sample size")).toBeVisible();
  await capture(page, "desktop-playbook-detail.png");

  await page.goto("/review");
  await expect(page.getByRole("heading", { name: "Review Queue" })).toBeVisible();
  await capture(page, "desktop-review-queue.png");

  await page.goto("/reviews/weekly/2026-07-27");
  await expect(page.getByText("Written review")).toBeVisible();
  await capture(page, "desktop-weekly-review.png");
  await page.goto("/reviews/monthly/2026-07-01");
  await expect(page.getByText("Written review")).toBeVisible();
  await capture(page, "desktop-monthly-review.png");

  await page.goto("/accounts");
  await page.locator('a[href^="/accounts/"]').first().click();
  await expect(page.getByRole("heading", { name: "Prop account profile" })).toBeVisible();
  await capture(page, "desktop-prop-account.png");

  await page.goto("/imports");
  await expect(page.getByRole("heading", { name: "Imports & data quality" })).toBeVisible();
  await capture(page, "desktop-import-history.png");

  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
  await capture(page, "desktop-settings.png");
});

test("Phase 2 iPhone workflows have no horizontal overflow", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "mobile-safari", "Mobile visual acceptance.");
  const pages = [
    ["/", "mobile-home.png"],
    ["/timeline/2026-07-29", "mobile-trading-day.png"],
    ["/review", "mobile-review-queue.png"],
    ["/calendar", "mobile-calendar.png"],
    ["/settings", "mobile-settings.png"],
  ] as const;
  for (const [url, screenshot] of pages) {
    await page.goto(url);
    await expect(page.locator("h1").first()).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    );
    expect(overflow, `${url} should not overflow horizontally`).toBe(false);
    await capture(page, screenshot);
  }

  await page.goto("/trades");
  await Promise.all([
    page.waitForURL(/\/trades\/[^/]+$/),
    page.locator('.trade-cards a[href^="/trades/"]').first().click(),
  ]);
  await expect(page.getByText("Focused trade review")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    ),
  ).toBe(false);
  await capture(page, "mobile-trade-review.png");

  await page.goto("/accounts");
  await page.locator('a[href^="/accounts/"]').first().click();
  await expect(page.getByRole("heading", { name: "Prop account profile" })).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    ),
  ).toBe(false);
  await capture(page, "mobile-prop-account.png");
});
