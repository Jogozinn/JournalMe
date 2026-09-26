import path from "node:path";

import { expect, test } from "@playwright/test";

const reports = [
  "Performance.csv",
  "Position History.csv",
  "Fills.csv",
  "Orders (1).csv",
  "Cash History.csv",
  "Account Balance History.csv",
  "Order Details.csv",
].map((filename) => path.resolve(process.cwd(), "..", filename));

test("real API re-upload remains idempotent and journal views load", async ({
  page,
}, testInfo) => {
  test.skip(
    process.env.JOURNALME_REAL_E2E !== "1" ||
      testInfo.project.name !== "desktop",
    "Runs only against explicitly started local API and frontend processes.",
  );

  await page.goto("/import");
  await page.locator('input[type="file"]').setInputFiles(reports);
  await page.getByRole("button", { name: "Review import" }).click();

  await expect(page.getByText("0 new canonical trades")).toBeVisible();
  await expect(page.getByText("Canceled/unfilled retained")).toBeVisible();
  await expect(page.getByText("Unmatched filled orders")).toBeVisible();

  await page.getByRole("button", { name: "Confirm atomic import" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { name: "Welcome back." })).toBeVisible();

  await page.getByRole("link", { name: "Trades" }).first().click();
  await expect(page.getByText("12 normalized trades")).toBeVisible();

  await page.getByRole("link", { name: "Calendar" }).first().click();
  const tradingDay = page.locator(".calendar-cell.active-day").first();
  await expect(tradingDay).toBeVisible();
  await tradingDay.click();
  await expect(page.getByText("Session story")).toBeVisible();
});
