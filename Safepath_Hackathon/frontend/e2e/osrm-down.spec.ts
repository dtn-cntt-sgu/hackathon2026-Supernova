import { test, expect } from "@playwright/test";

// Run only after stopping the real OSRM container; no API interception.
test("provider outage never draws a fabricated route", async ({ page }) => {
  test.skip(process.env.OSRM_DOWN_TESTS !== "1", "Run with OSRM_DOWN_TESTS=1 after docker compose stop osrm");
  await page.goto("/map");
  await expect(page.getByText(/ROUTING_PROVIDER_UNAVAILABLE/)).toBeVisible();
  await expect(page.getByText("Tuyến đang chọn")).toHaveCount(0);
  await expect(page.locator("[data-route-vertices]")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Thử lại" })).toBeVisible();
  await page.screenshot({ path: "test-results/osrm-provider-down.png", fullPage: true });
});
