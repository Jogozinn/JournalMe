import path from "node:path";

import { expect, test } from "@playwright/test";

const output = path.resolve(process.cwd(), "artifacts", "prop-rules");

test.beforeEach(({}, testInfo) => {
  test.skip(
    process.env.JOURNALME_REAL_E2E !== "1",
    "Runs only against the explicitly started real-data acceptance stack.",
  );
  testInfo.setTimeout(90_000);
});

test("LucidFlex tracker renders nullable rules and payout-cycle status", async ({
  page,
}, testInfo) => {
  await page.goto("/accounts");
  await page.locator('a[href^="/accounts/"]').first().click();
  await expect(
    page.getByRole("heading", { name: "Prop account profile" }),
  ).toBeVisible();

  await expect(page.getByLabel(/Profit target/)).toHaveValue("");
  await expect(page.getByLabel(/Daily loss limit/)).toHaveValue("");
  await expect(page.getByLabel(/Consistency %/)).toHaveValue("");
  await expect(page.getByLabel("Minimum trading days")).toHaveValue("");
  await expect(page.getByLabel(/Payout buffer/)).toHaveValue("");

  await expect(page.getByText("1 / 5", { exact: true })).toBeVisible();
  await expect(page.getByText("4 minis / 40 micros")).toBeVisible();
  await expect(page.getByText("$1,060.85")).toBeVisible();
  await expect(page.getByText("$954.77")).toBeVisible();
  await expect(page.getByText("Not eligible yet.")).toBeVisible();
  await expect(page.getByText("Not applicable", { exact: true })).toHaveCount(4);

  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth >
        document.documentElement.clientWidth,
    ),
  ).toBe(false);
  await page.screenshot({
    path: path.join(
      output,
      testInfo.project.name === "desktop"
        ? "desktop-lucidflex-prop-tracker.png"
        : "mobile-lucidflex-prop-tracker.png",
    ),
    fullPage: true,
  });
});
