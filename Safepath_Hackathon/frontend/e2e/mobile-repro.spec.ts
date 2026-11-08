import { test, expect } from "@playwright/test";

const VIEWPORTS = [
  { width: 360, height: 800, name: "360x800-portrait" },
  { width: 375, height: 667, name: "375x667-portrait" },
  { width: 390, height: 844, name: "390x844-portrait" },
  { width: 412, height: 915, name: "412x915-portrait" },
  { width: 844, height: 390, name: "844x390-landscape" },
];

test.describe("Reproduce Confirmed Bugs & Verify Fixes", () => {
  for (const vp of VIEWPORTS) {
    test(`Bug A & B verification on ${vp.name}`, async ({ page }) => {
      test.setTimeout(45000);
      page.on('console', msg => console.log(`[${vp.name}] LOG:`, msg.text().slice(0, 120)));
      page.on('pageerror', err => console.log(`[${vp.name}] PAGE ERROR:`, err.message));

      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.addInitScript(() => {
        localStorage.setItem('safepath_tour_state_v1', JSON.stringify({ version: 'v1', status: 'skipped', updatedAt: new Date().toISOString() }));
      });
      await page.goto("/map");

      // Dismiss onboarding welcome if opened
      const welcomeDialog = page.locator("[role='dialog'][aria-labelledby='onboarding-welcome-title']");
      if (await welcomeDialog.isVisible({ timeout: 1500 }).catch(() => false)) {
        await welcomeDialog.getByRole("button", { name: "Bỏ qua" }).click();
      }

      await expect(page.locator(".floating-navigator")).toBeVisible({ timeout: 20000 });
      await expect(page.locator(".map-camera-controls")).toBeVisible({ timeout: 20000 });

      // BUG A: Camera switch hit-testing
      const cameraSwitch = page.getByRole("switch", { name: "Hiển thị camera" });
      await expect(cameraSwitch).toBeVisible();

      const switchBox = await cameraSwitch.boundingBox();
      expect(switchBox).not.toBeNull();
      expect(switchBox!.height).toBeGreaterThanOrEqual(44); // Meets touch target minimum
      const centerX = switchBox!.x + switchBox!.width / 2;
      const centerY = switchBox!.y + switchBox!.height / 2;

      const hitElementTag = await page.evaluate(
        ({ x, y }) => {
          const el = document.elementFromPoint(x, y);
          return el ? `${el.tagName}: ${el.textContent?.trim().slice(0, 20)}` : null;
        },
        { x: centerX, y: centerY }
      );

      console.log(`[${vp.name}] Hit element at center of camera switch: ${hitElementTag}`);
      // Must NOT be the header, onboarding button, or HUD!
      expect(hitElementTag).not.toContain("Hướng dẫn");

      // Verify toggle click at center changes aria-checked
      await page.mouse.click(centerX, centerY);
      await expect(cameraSwitch).toHaveAttribute("aria-checked", "false");

      // Restore
      const switchBox2 = await cameraSwitch.boundingBox();
      expect(switchBox2).not.toBeNull();
      await page.mouse.click(switchBox2!.x + switchBox2!.width / 2, switchBox2!.y + switchBox2!.height / 2);
      await expect(cameraSwitch).toHaveAttribute("aria-checked", "true");

      // BUG B: Sheet expansion geometry on portrait
      if (vp.height > 500) {
        const sheet = page.locator(".floating-navigator");
        const heightBefore = (await sheet.boundingBox())!.height;
        expect(heightBefore).toBeLessThanOrEqual(100);

        const expandBtn = page.getByRole("button", { name: "Mở bảng tuyến đường" });
        await expandBtn.click();
        await page.waitForTimeout(400);

        const heightAfter = (await sheet.boundingBox())!.height;
        console.log(`[${vp.name}] Sheet height before: ${heightBefore}px, after: ${heightAfter}px`);

        // Height must actually expand (not locked at 247px or 280px)
        expect(heightAfter).toBeGreaterThan(heightBefore + 200);
        await expect(page.getByRole("button", { name: "Thu gọn bảng tuyến đường" })).toHaveAttribute("aria-expanded", "true");
      }
    });
  }
});
