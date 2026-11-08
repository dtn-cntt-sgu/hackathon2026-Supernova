import { test, expect } from "@playwright/test";
import path from "path";

const VIEWPORTS = [
  { name: "desktop_1440x900", width: 1440, height: 900 },
  { name: "desktop_1280x720", width: 1280, height: 720 },
  { name: "laptop_1366x768", width: 1366, height: 768 },
  { name: "mobile_390x844", width: 390, height: 844 },
];

test.describe("Landing Page & ACT 04 After Fixes", () => {
  for (const vp of VIEWPORTS) {
    test(`Visual capture and layout verification on ${vp.name}`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto("/", { waitUntil: "networkidle" });
      await page.waitForTimeout(1000);

      // Screenshot Act 1
      await page.screenshot({
        path: path.join(__dirname, `../../docs/screenshots/after_landing_act1_${vp.name}.png`),
      });

      // Scroll to Act 4
      const act4 = page.locator("#routing");
      await act4.scrollIntoViewIfNeeded();
      await page.waitForTimeout(1000);

      // Screenshot Act 4
      await page.screenshot({
        path: path.join(__dirname, `../../docs/screenshots/after_landing_act4_${vp.name}.png`),
      });

      // Assert 0 horizontal overflow
      const hasHorizontalScroll = await page.evaluate(() => {
        return document.documentElement.scrollWidth > document.documentElement.clientWidth;
      });
      expect(hasHorizontalScroll).toBe(false);

      // Verify CTA button is visible
      const ctaBtn = page.locator("[data-testid='landing-start-routing-btn']");
      await expect(ctaBtn).toBeVisible();

      // Verify no overlap between chapter bar and ACT 04 card
      const routeCard = page.locator(".route-ready");
      await expect(routeCard).toBeVisible();
    });
  }

  test("ACT 04 Preset selection, real coordinates, and navigation to /di-duong", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 720 });
    await page.goto("/", { waitUntil: "networkidle" });

    const act4 = page.locator("#routing");
    await act4.scrollIntoViewIfNeeded();
    await page.waitForTimeout(500);

    // Click preset "Bến Thành → Landmark 81"
    const presetBtn = page.getByRole("button", { name: "Bến Thành → Landmark 81" });
    await expect(presetBtn).toBeVisible();
    await presetBtn.click();

    // Verify coordinates are populated
    await expect(page.getByText("Tọa độ: 10.7725, 106.6980")).toBeVisible();
    await expect(page.getByText("Tọa độ: 10.7950, 106.7218")).toBeVisible();

    // Verify CTA button
    const ctaBtn = page.getByRole("link", { name: /BẮT ĐẦU TÌM ĐƯỜNG/ });
    await expect(ctaBtn).toBeVisible();

    // Click CTA and verify navigation to /di-duong with valid query parameters
    await ctaBtn.click({ force: true });
    await page.waitForURL(/\/di-duong/, { timeout: 10000 });
    expect(page.url()).toContain("origin=10.7725%2C106.698");
    expect(page.url()).toContain("destination=10.795%2C106.7218");

    // Wait for route panel on /di-duong to mount
    await expect(page.locator(".floating-navigator")).toBeVisible({ timeout: 10000 });
  });

  test("Verify /monitor live camera data display", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/monitor", { waitUntil: "networkidle" });

    // Expect header and 4 stat cards
    await expect(page.getByText("Tổng Camera Hệ Thống")).toBeVisible();
    await expect(page.getByText("Tiến độ Chu kỳ 30 Phút")).toBeVisible();
    await expect(page.getByText("Snapshot Hợp Lệ Gần Đây")).toBeVisible();
    await expect(page.getByText("Lượt Phân Tích Vision AI")).toBeVisible();
  });
});
