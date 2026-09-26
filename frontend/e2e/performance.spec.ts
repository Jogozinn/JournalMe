import { expect, test } from "@playwright/test";

const accountId = "c777b1ea-e964-4860-8df3-68f5da57d534";
const runPerformance = process.env.JOURNALME_PERF_E2E === "1";
const apiUrl = process.env.JOURNALME_API_URL ?? "http://127.0.0.1:8066";

test.describe("production navigation timing", () => {
  test.skip(!runPerformance, "Set JOURNALME_PERF_E2E=1 against a production server.");

  test.beforeEach(async ({ page }) => {
    await page.addInitScript((id) => {
      window.localStorage.setItem("journalme-account", id);
    }, accountId);
  });

  test("prefetched routes stay client-side and avoid duplicate account loads", async ({ page }) => {
    let accountRequests = 0;
    page.on("request", (request) => {
      if (new URL(request.url()).pathname === "/api/v1/accounts") {
        accountRequests += 1;
      }
    });
    await page.goto("/");
    await expect(page.getByText("$51,748.25", { exact: true })).toBeVisible();
    await page.waitForTimeout(250);

    const started = performance.now();
    await page.getByRole("link", { name: "Trades", exact: true }).first().click();
    await expect(page).toHaveURL(/\/trades$/);
    await expect(page.getByRole("heading", { name: /Trades/i })).toBeVisible();
    const elapsed = performance.now() - started;

    expect(elapsed).toBeLessThan(700);
    expect(accountRequests).toBe(1);
    expect(
      await page.evaluate(() => performance.getEntriesByType("navigation").length),
    ).toBe(1);
  });

  test("core APIs meet the local production budget", async ({ request }) => {
    const paths = [
      `/api/v1/dashboard?account_id=${accountId}`,
      `/api/v1/trades?account_id=${accountId}&page=1&page_size=50`,
      `/api/v1/calendar?account_id=${accountId}&year=2026&month=7`,
    ];
    for (const path of paths) {
      const started = performance.now();
      const response = await request.get(`${apiUrl}${path}`);
      const elapsed = performance.now() - started;
      expect(response.ok()).toBeTruthy();
      expect(elapsed, path).toBeLessThan(250);
    }
    const analyticsStart = performance.now();
    const analytics = await request.get(
      `${apiUrl}/api/v1/analytics?account_id=${accountId}`,
    );
    expect(analytics.ok()).toBeTruthy();
    expect(performance.now() - analyticsStart).toBeLessThan(500);
  });
});
