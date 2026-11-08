import { test, expect } from "@playwright/test";

const VIEWPORTS = [
  { name: "375px_mobile_se", width: 375, height: 667 },
  { name: "390px_mobile_modern", width: 390, height: 844 },
  { name: "768px_tablet", width: 768, height: 1024 },
  { name: "1024px_laptop", width: 1024, height: 768 },
  { name: "1440px_desktop", width: 1440, height: 900 },
];

test.describe("SafePath AI — Header Layout & UI Regression Audit", () => {
  for (const vp of VIEWPORTS) {
    test(`Header on /monitor at ${vp.name} (${vp.width}x${vp.height})`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto("/monitor");
      await page.waitForLoadState("domcontentloaded");

      // Verify Header exists, is sticky/visible
      const header = page.locator("header");
      await expect(header).toBeVisible();

      // Verify no horizontal overflow
      const hasOverflow = await page.evaluate(() => {
        return document.documentElement.scrollWidth > window.innerWidth;
      });
      expect(hasOverflow).toBe(false);

      // Verify Brand Logo is visible
      const brandLogo = page.locator("header a[aria-label='SafePathAI Trang chủ']");
      await expect(brandLogo).toBeVisible();

      if (vp.width >= 768) {
        // Desktop nav links visible
        const nav = page.locator("header nav[aria-label='Điều hướng chính']");
        await expect(nav).toBeVisible();

        // Active link on /monitor
        const activeLink = page.locator("header nav a[href='/monitor'][aria-current='page']");
        await expect(activeLink).toBeVisible();
        await expect(activeLink).toHaveText("Camera");
      } else {
        // Mobile view: hamburger menu button exists and can be clicked
        const menuBtn = page.locator("[data-testid='mobile-menu-btn']");
        await expect(menuBtn).toBeVisible();

        // Click to open menu
        await menuBtn.click();
        const drawer = page.locator("[data-testid='mobile-menu-drawer']");
        await expect(drawer).toBeVisible();

        // Active link in drawer
        const drawerActive = drawer.locator("a[href='/monitor'][aria-current='page']");
        await expect(drawerActive).toBeVisible();

        // Close menu
        await menuBtn.click();
      }

      // Capture screenshot
      await page.waitForTimeout(500);
      await page.screenshot({
        path: `docs/screenshots/audit_monitor_${vp.name}.png`,
        fullPage: false,
      });
    });
  }

  test("Smoke audit across all core pages for layout regressions", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });

    const pages = [
      { url: "/", name: "landing", selector: "#city" },
      { url: "/di-duong", name: "di_duong", selector: ".floating-navigator" },
      { url: "/news", name: "news", selector: "header" },
      { url: "/dashboard", name: "dashboard", selector: "header" },
      { url: "/account", name: "account", selector: "header" },
    ];

    for (const p of pages) {
      await page.goto(p.url);
      await page.waitForLoadState("domcontentloaded");
      await expect(page.locator(p.selector)).toBeVisible();

      // Check horizontal overflow
      const hasOverflow = await page.evaluate(() => {
        return document.documentElement.scrollWidth > window.innerWidth;
      });
      expect(hasOverflow).toBe(false);

      await page.waitForTimeout(600);
      await page.screenshot({
        path: `docs/screenshots/audit_${p.name}_1440px.png`,
        fullPage: false,
      });
    }
  });
});
