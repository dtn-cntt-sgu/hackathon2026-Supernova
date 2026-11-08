import { test, expect } from "@playwright/test";

test.describe("SafePath AI — Light Cinematic 3D Experience", () => {
  test("Landing Page renders daylight 3D city and Act 1 heading", async ({ page }) => {
    await page.goto("/");
    await page.waitForLoadState("domcontentloaded");

    // Check Act 1 heading: THÀNH PHỐ KHÔNG BAO GIỜ ĐỨNG YÊN.
    const heading = page.locator("#city h1");
    await expect(heading).toBeVisible();
    await expect(heading).toContainText("THÀNH PHỐ");
    await expect(heading).toContainText("KHÔNG BAO GIỜ ĐỨNG YÊN");

    // Check CTA button navigates to /di-duong
    const cta = page.locator("#city a[href='/di-duong']");
    await expect(cta).toBeVisible();

    // Check 3D Canvas
    const canvasContainer = page.locator(".observatory-map-canvas");
    await expect(canvasContainer).toBeVisible();

    // Capture desktop screenshot
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.waitForTimeout(1000);
    await page.screenshot({ path: "docs/screenshots/light_cinematic_landing_desktop.png", fullPage: false });

    // Capture mobile screenshot
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(500);
    await page.screenshot({ path: "docs/screenshots/light_cinematic_landing_mobile.png", fullPage: false });
  });

  test("Route /di-duong loads tactical navigation HUD and map", async ({ page }) => {
    await page.goto("/di-duong");
    await page.waitForLoadState("domcontentloaded");

    // Check floating navigator
    const navigator = page.locator("aside.floating-navigator");
    await expect(navigator).toBeVisible();

    // Check search button
    const searchBtn = page.locator("[data-tour='search-route-btn']");
    await expect(searchBtn).toBeVisible();

    // Check map container
    const map = page.locator(".spatial-map");
    await expect(map).toBeVisible();

    // Capture desktop screenshot
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.waitForTimeout(1500);
    await page.screenshot({ path: "docs/screenshots/light_cinematic_di_duong_desktop.png", fullPage: false });

    // Capture mobile screenshot
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(1000);
    await page.screenshot({ path: "docs/screenshots/light_cinematic_di_duong_mobile.png", fullPage: false });
  });

  test("Auxiliary Pages render in Light Glassmorphism", async ({ page }) => {
    // 1. /monitor
    await page.goto("/monitor");
    await page.waitForLoadState("domcontentloaded");
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.waitForTimeout(1000);
    await page.screenshot({ path: "docs/screenshots/light_cinematic_monitor_desktop.png", fullPage: false });

    // 2. /news
    await page.goto("/news");
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(1000);
    await page.screenshot({ path: "docs/screenshots/light_cinematic_news_desktop.png", fullPage: false });

    // 3. /dashboard
    await page.goto("/dashboard");
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(1000);
    await page.screenshot({ path: "docs/screenshots/light_cinematic_dashboard_desktop.png", fullPage: false });
  });
});

