import { test, expect } from "@playwright/test";
import path from "path";

const VIEWPORTS = [
  { name: "desktop_1440x900", width: 1440, height: 900 },
  { name: "desktop_1280x720", width: 1280, height: 720 },
  { name: "laptop_1366x768", width: 1366, height: 768 },
  { name: "mobile_390x844", width: 390, height: 844 },
];

test.describe("Landing Page & ACT 04 Audit Before Fixes", () => {
  for (const vp of VIEWPORTS) {
    test(`Capture Landing & ACT 04 on ${vp.name}`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto("/", { waitUntil: "networkidle" });
      await page.waitForTimeout(1000);

      // Screenshot Act 1
      await page.screenshot({
        path: path.join(__dirname, `../../docs/screenshots/before_landing_act1_${vp.name}.png`),
      });

      // Scroll to Act 4
      const act4 = page.locator("#routing");
      await act4.scrollIntoViewIfNeeded();
      await page.waitForTimeout(1000);

      // Screenshot Act 4
      await page.screenshot({
        path: path.join(__dirname, `../../docs/screenshots/before_landing_act4_${vp.name}.png`),
      });

      // Check overflow
      const hasHorizontalScroll = await page.evaluate(() => {
        return document.documentElement.scrollWidth > document.documentElement.clientWidth;
      });
      console.log(`[${vp.name}] Has horizontal scroll:`, hasHorizontalScroll);
    });
  }
});

