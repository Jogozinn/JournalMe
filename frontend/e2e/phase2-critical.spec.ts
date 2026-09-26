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

test("professional journal critical flow", async ({ page, request }, testInfo) => {
  test.skip(
    process.env.JOURNALME_PHASE2_MUTATING_E2E !== "1" ||
      testInfo.project.name !== "desktop",
    "Runs only against an isolated database copy.",
  );
  test.setTimeout(180_000);

  await page.goto("/review");
  await expect(page.getByText("12 unreviewed")).toBeVisible();

  await page.goto("/trades");
  await Promise.all([
    page.waitForURL(/\/trades\/[^/]+$/),
    page.locator('.trade-table a[href^="/trades/"]').first().click(),
  ]);
  await page.getByLabel("Trade thesis").fill("Structured reversal at a defined level.");
  await page.getByLabel("Why did you enter?").fill("Confirmation aligned with the written plan.");
  await page.getByLabel("Why did you exit?").fill("Invalidation was reached.");
  await page.getByLabel("Lesson to carry forward").fill("Keep the same predefined risk.");
  await page.getByLabel("Trade grade").selectOption("B");
  await page.getByLabel("Followed plan").selectOption("true");
  await page.getByLabel("Playbook").selectOption({ index: 1 });
  for (const checkbox of await page.locator(".check-response input").all()) {
    await checkbox.check();
  }
  await page.locator(".tag-editor label", { hasText: /^ORB$/ }).click();
  await page.getByRole("button", { name: "Save review" }).click();
  await expect(page.getByText("Review requirements complete.")).toBeVisible();

  await page.goto("/review");
  await expect(page.getByText("11 unreviewed")).toBeVisible();

  await page.goto("/timeline/2026-07-29");
  await page.getByLabel("Reflection").fill("The session was profitable, but process remains the review focus.");
  await page.getByLabel("Focus for next session").fill("Repeat defined entries and risk.");
  await page.getByLabel("Followed daily rules").selectOption("true");
  await page.getByLabel("Day grade").selectOption("B");
  await Promise.all([
    page.waitForResponse((response) =>
      response.url().includes("/journals/daily/2026-07-29") &&
      response.request().method() === "PUT",
    ),
    page.getByRole("button", { name: "Save daily journal" }).click(),
  ]);

  await page.goto("/reviews/weekly/2026-07-27");
  await page.getByLabel("Overall review").fill("A useful week with clear review work remaining.");
  await page.getByLabel("What worked").fill("Defined risk.");
  await page.getByLabel("What failed").fill("Incomplete reviews.");
  await page.getByLabel("Next week focus").fill("Complete reviews the same day.");
  await page.getByLabel("Next week goals").fill("Follow the primary playbook.");
  await page.getByLabel("Grade").selectOption("B");
  await page.getByRole("button", { name: "Save weekly review" }).click();
  await expect(page.getByText("Saved", { exact: true })).toBeVisible();

  await page.goto("/goals");
  await page.getByRole("button", { name: "Create goal" }).click();
  await page.getByLabel("Goal type").selectOption("pnl_target");
  await page.getByLabel("Target value").fill("3000");
  await page.getByLabel("Personal wording").fill("Trade the plan for the full month.");
  await page.locator("form").getByRole("button", { name: "Create goal" }).click();
  await expect(page.getByText("Trade the plan for the full month.")).toBeVisible();

  await page.goto("/accounts");
  await page.locator('a[href^="/accounts/"]').first().click();
  await page.getByLabel("Firm name").fill("Agreement-defined firm");
  await page.getByLabel("Profit target").fill("3000");
  await page.getByLabel("Maximum loss").fill("2000");
  await page.getByRole("button", { name: /Enable prop tracking|Update prop rules/ }).click();
  await expect(page.getByText("Account in progress")).toBeVisible();
  await expect(page.getByText(/profit remaining/i).first()).toBeVisible();

  await page.goto("/manual-trade");
  await page.getByLabel("Symbol", { exact: true }).fill("MESU6");
  await page.getByLabel("Quantity").fill("1");
  await page.getByLabel(/Entry time/).fill("2026-07-30T10:00");
  await page.getByLabel(/Exit time/).fill("2026-07-30T10:05");
  await page.getByLabel("Entry price").fill("5000");
  await page.getByLabel("Exit price").fill("5001");
  await page.getByLabel("Gross P&L").fill("5");
  await page.getByLabel("Fees").fill("1");
  await page.getByRole("button", { name: "Create manual trade" }).click();
  await expect(page.getByText("manual", { exact: false }).first()).toBeVisible();

  const accountsResponse = await request.get("http://127.0.0.1:8200/api/v1/accounts");
  const accountId = (await accountsResponse.json())[0].id;
  const exportResponse = await request.get(
    `http://127.0.0.1:8200/api/v1/exports/trades.csv?account_id=${accountId}`,
  );
  expect(exportResponse.ok()).toBe(true);
  expect(await exportResponse.text()).toContain("source");

  await page.goto("/import");
  await page.locator('input[type="file"]').setInputFiles(reports);
  await page.getByRole("button", { name: "Review import" }).click();
  await expect(page.getByText("0 new canonical trades")).toBeVisible();
});
