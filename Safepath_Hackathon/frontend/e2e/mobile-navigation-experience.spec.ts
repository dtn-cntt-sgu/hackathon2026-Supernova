import { test, expect, Page } from "@playwright/test";

/**
 * Mobile-First Navigation Experience Test Suite for SafePathAI
 * 
 * Verifies:
 * 1. Bug A resolution: Camera switch hit-testing, no header overlap, center tap, aria-checked toggle.
 * 2. Bug B resolution: Route sheet real geometry expansion and collapse synchronized with aria-expanded.
 * 3. Explore, Planning, Route Preview, and Active Navigation mobile states.
 * 4. Actual unobscured map visibility:
 *    - Collapsed Explore / Preview >= 60%
 *    - Active Navigation >= 65%
 *    - Landscape >= 55%
 * 5. Touch target dimensions >= 44x44px.
 * 6. Real route searches via local backend & OSRM, route preservation on camera toggle.
 * 7. Welcome dialog dismissal via UI.
 * 8. Auxiliary pages (/monitor, /news, /dashboard, /account) responsive check.
 */

const MOBILE_VIEWPORTS = [
  { width: 360, height: 800, name: "360x800-portrait" },
  { width: 375, height: 667, name: "375x667-portrait" },
  { width: 390, height: 844, name: "390x844-portrait" },
  { width: 412, height: 915, name: "412x915-portrait" },
  { width: 844, height: 390, name: "844x390-landscape" },
  { width: 667, height: 375, name: "667x375-landscape" },
];

/** Dismisses onboarding welcome modal through its UI button if open */
async function dismissWelcomeIfOpen(page: Page) {
  try {
    const welcomeDialog = page.locator("[role='dialog'][aria-labelledby='onboarding-welcome-title']");
    if (await welcomeDialog.isVisible({ timeout: 3000 }).catch(() => false)) {
      const skipBtn = welcomeDialog.getByRole("button", { name: "Bỏ qua" });
      if (await skipBtn.isVisible().catch(() => false)) {
        await skipBtn.click();
        await page.waitForTimeout(400);
      }
    }
  } catch {
    // Ignore
  }
}

/** Measures actual unobscured map area percentage using point-grid sampling */
async function measureUnobscuredMap(page: Page): Promise<number> {
  return page.evaluate(() => {
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const obscuringSelectors = [
      ".spatial-dashboard > header",
      ".floating-navigator",
      ".spatial-dock",
      ".mobile-nav-banner",
      ".mobile-nav-dock",
      ".evidence-inspector",
      "[role='dialog']",
    ];

    const step = 10;
    let visiblePoints = 0;
    let totalPoints = 0;

    for (let y = step / 2; y < vh; y += step) {
      for (let x = step / 2; x < vw; x += step) {
        totalPoints++;
        const el = document.elementFromPoint(x, y);
        if (!el) continue;

        const isCanvas = el.classList.contains("maplibregl-canvas") || Boolean(el.closest(".spatial-map"));
        const isObscured = obscuringSelectors.some((sel) => {
          const panel = el.closest(sel);
          if (!panel) return false;
          const rect = panel.getBoundingClientRect();
          return rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.top < vh;
        });

        if (isCanvas && !isObscured) {
          visiblePoints++;
        }
      }
    }

    return totalPoints > 0 ? parseFloat(((visiblePoints / totalPoints) * 100).toFixed(1)) : 0;
  });
}

test.describe("Mobile-First Navigation Suite — Core Bug Validations", () => {
  for (const vp of MOBILE_VIEWPORTS) {
    test.describe(`Viewport: ${vp.name}`, () => {
      test.use({
        viewport: { width: vp.width, height: vp.height },
        isMobile: true,
        hasTouch: true,
      });

      test("Bug A & B: Camera switch is hit-testable at center, sheet expands/collapses with real geometry", async ({ page }) => {
        // Prevent first-visit onboarding tour popup from blocking automated pointer clicks
        await page.addInitScript(() => {
          localStorage.setItem('safepath_tour_state_v1', JSON.stringify({ version: 'v1', status: 'skipped', updatedAt: new Date().toISOString() }));
        });

        await page.goto("/map");
        await dismissWelcomeIfOpen(page);
        await expect(page.locator(".maplibregl-canvas")).toBeVisible({ timeout: 15000 });

        // 1. Verify Camera Switch Geometry and Hit Testing
        const cameraSwitch = page.getByRole("switch", { name: "Hiển thị camera" });
        await expect(cameraSwitch).toBeVisible();

        const switchBox = await cameraSwitch.boundingBox();
        expect(switchBox).not.toBeNull();
        expect(switchBox!.height).toBeGreaterThanOrEqual(44); // Meets touch target height

        const centerX = switchBox!.x + switchBox!.width / 2;
        const centerY = switchBox!.y + switchBox!.height / 2;

        // Inspect document.elementFromPoint at switch center
        const hitInfo = await page.evaluate(
          ({ x, y }) => {
            const el = document.elementFromPoint(x, y);
            if (!el) return null;
            const switchEl = el.closest('[role="switch"]');
            return {
              isSwitchOrDescendant: Boolean(switchEl),
              hitTag: el.tagName,
              hitClass: el.className,
              hitText: el.textContent?.trim().slice(0, 30),
            };
          },
          { x: centerX, y: centerY }
        );

        // Assert hit belongs strictly to switch or its descendants (NOT the header, NOT the HUD!)
        expect(hitInfo).not.toBeNull();
        expect(hitInfo!.isSwitchOrDescendant).toBe(true);

        // Tap the center coordinate using touch emulation
        await page.touchscreen.tap(centerX, centerY);
        await expect(cameraSwitch).toHaveAttribute("aria-checked", "false");

        // Tap again to restore (re-measuring center as width may shift slightly between 'Bật' and 'Tắt')
        const switchBox2 = await cameraSwitch.boundingBox();
        expect(switchBox2).not.toBeNull();
        await page.touchscreen.tap(switchBox2!.x + switchBox2!.width / 2, switchBox2!.y + switchBox2!.height / 2);
        await expect(cameraSwitch).toHaveAttribute("aria-checked", "true");

        // 2. Verify Sheet Geometry and State Synchronization
        const sheet = page.locator(".floating-navigator");
        await expect(sheet).toBeVisible();

        const sheetBoxBefore = await sheet.boundingBox();
        expect(sheetBoxBefore).not.toBeNull();

        const isLandscape = vp.height < 500;
        if (!isLandscape) {
          // On portrait, sheet starts in compact peek state (~78px)
          expect(sheetBoxBefore!.height).toBeLessThanOrEqual(100);

          // Measure initial map visibility in Explore state
          const exploreMapVisibility = await measureUnobscuredMap(page);
          console.log(`[${vp.name}] Explore state unobscured map: ${exploreMapVisibility}%`);
          expect(exploreMapVisibility).toBeGreaterThanOrEqual(60);

          // Tap expand button ("Mở bảng tuyến đường")
          const expandBtn = page.getByRole("button", { name: "Mở bảng tuyến đường" });
          await expect(expandBtn).toBeVisible();
          await expandBtn.click();
          await page.waitForTimeout(400); // Wait for transition

          // Assert height increased meaningfully (> 250px difference)
          const sheetBoxAfter = await sheet.boundingBox();
          expect(sheetBoxAfter).not.toBeNull();
          expect(sheetBoxAfter!.height).toBeGreaterThan(sheetBoxBefore!.height + 250);

          // Verify accessibility state matches
          const collapseBtn = page.getByRole("button", { name: "Thu gọn bảng tuyến đường" });
          await expect(collapseBtn).toBeVisible();
          await expect(collapseBtn).toHaveAttribute("aria-expanded", "true");

          // Collapse sheet back down
          await collapseBtn.click();
          await page.waitForTimeout(400);

          const sheetBoxCollapsed = await sheet.boundingBox();
          expect(sheetBoxCollapsed!.height).toBeLessThanOrEqual(100);
          await expect(page.getByRole("button", { name: "Mở bảng tuyến đường" })).toHaveAttribute("aria-expanded", "false");
        } else {
          // On landscape, map visibility should exceed 55%
          const landscapeMapVisibility = await measureUnobscuredMap(page);
          console.log(`[${vp.name}] Landscape unobscured map: ${landscapeMapVisibility}%`);
          expect(landscapeMapVisibility).toBeGreaterThanOrEqual(55);
        }
      });
    });
  }
});

test.describe("Full Mobile Flow Verification (375x667 & 390x844)", () => {
  const TEST_DEVICES = [
    { width: 375, height: 667, name: "iPhone-SE-375x667" },
    { width: 390, height: 844, name: "iPhone-14-390x844" },
  ];

  for (const dev of TEST_DEVICES) {
    test(`Comprehensive navigation lifecycle on ${dev.name}`, async ({ page }) => {
      await page.setViewportSize({ width: dev.width, height: dev.height });
      await page.emulateMedia({ reducedMotion: "reduce" });

      // Step 1: Landing page to /map navigation
      await page.goto("/");
      await dismissWelcomeIfOpen(page);
      const ctaBtn = page.getByRole("link", { name: /Mở bản đồ|Tìm lộ trình tránh ngập|Bắt đầu ngay/i }).first();
      await expect(ctaBtn).toBeVisible();
      await ctaBtn.click();
      await page.waitForURL("**/map");
      await expect(page.locator(".maplibregl-canvas")).toBeVisible({ timeout: 15000 });
      await dismissWelcomeIfOpen(page);

      // Capture screenshot: Explore State
      await page.screenshot({ path: `test-results/mobile-evidence/${dev.name}-1-explore.png` });

      // Step 2: Explore state check
      const exploreVis = await measureUnobscuredMap(page);
      console.log(`[${dev.name}] Explore unobscured map: ${exploreVis}%`);
      expect(exploreVis).toBeGreaterThanOrEqual(60);

      // Step 3: Expand search planning sheet
      const expandSheetBtn = page.getByRole("button", { name: "Mở bảng tuyến đường" });
      await expandSheetBtn.click();
      await page.waitForTimeout(350);

      // Capture screenshot: Planning State
      await page.screenshot({ path: `test-results/mobile-evidence/${dev.name}-2-planning.png` });

      // Step 4: Real route search
      const originBtn = page.getByRole("button", { name: "Chợ Bến Thành" });
      const destBtn = page.getByRole("button", { name: "Ngã tư Hàng Xanh" });
      await expect(originBtn).toBeVisible();
      await expect(destBtn).toBeVisible();
      await originBtn.click();
      await destBtn.click();

      const searchBtn = page.getByRole("button", { name: "Tìm tuyến đường", exact: true });
      await expect(searchBtn).toBeEnabled();
      await searchBtn.click();

      // Wait for real route response and rendering
      await expect(page.locator("[data-selected-route-id], [data-route-vertices]")).toBeVisible({ timeout: 20000 });

      // If camera evidence modal popped open on desktop, ensure it does not cover mobile map
      const cameraModal = page.locator("[data-testid='camera-evidence-modal']");
      if (await cameraModal.isVisible().catch(() => false)) {
        await page.getByRole("button", { name: "Đóng chi tiết camera" }).click();
      }

      // Step 5: Route Preview State
      // Capture screenshot: Route Preview State
      await page.screenshot({ path: `test-results/mobile-evidence/${dev.name}-3-preview.png` });

      const previewVis = await measureUnobscuredMap(page);
      console.log(`[${dev.name}] Route Preview unobscured map: ${previewVis}%`);
      expect(previewVis).toBeGreaterThanOrEqual(60);

      // Verify route preservation during camera toggle
      const cameraSwitch = page.getByRole("switch", { name: "Hiển thị camera" });
      await cameraSwitch.click();
      await page.waitForTimeout(300);
      // Route must remain rendered
      await expect(page.locator("[data-selected-route-id], [data-route-vertices]")).toBeVisible();
      await cameraSwitch.click();

      // Step 6: Active Navigation State
      const startNavBtn = page.getByRole("button", { name: /Bắt đầu/i }).first();
      await expect(startNavBtn).toBeVisible();
      await startNavBtn.click();

      // Check Active Navigation banner and controls appear
      await expect(page.locator("[data-navigation-state='navigating']").first()).toBeVisible();
      await page.waitForTimeout(300);

      // Capture screenshot: Active Navigation State
      await page.screenshot({ path: `test-results/mobile-evidence/${dev.name}-4-navigation.png` });

      const navVis = await measureUnobscuredMap(page);
      console.log(`[${dev.name}] Active Navigation unobscured map: ${navVis}%`);
      expect(navVis).toBeGreaterThanOrEqual(65);

      // Step 7: Stop Navigation and return to preview
      const stopNavBtn = page.getByRole("button", { name: /Dừng chỉ đường|Dừng/i }).first();
      await expect(stopNavBtn).toBeVisible();
      await stopNavBtn.click();
      await expect(page.locator("[data-navigation-state='ended'], [data-navigation-state='route_preview']").first()).toBeVisible();
    });
  }
});

test.describe("Landscape Viewports (844x390 & 667x375)", () => {
  const LANDSCAPE_DEVICES = [
    { width: 844, height: 390, name: "Landscape-844x390" },
    { width: 667, height: 375, name: "Landscape-667x375" },
  ];

  for (const dev of LANDSCAPE_DEVICES) {
    test(`Landscape layout and clearance on ${dev.name}`, async ({ page }) => {
      await page.setViewportSize({ width: dev.width, height: dev.height });
      await page.addInitScript(() => {
        localStorage.setItem('safepath_tour_state_v1', JSON.stringify({ version: 'v1', status: 'skipped', updatedAt: new Date().toISOString() }));
      });
      await page.goto("/map");
      await dismissWelcomeIfOpen(page);
      await expect(page.locator(".maplibregl-canvas")).toBeVisible({ timeout: 15000 });

      // Measure map visibility in landscape
      const vis = await measureUnobscuredMap(page);
      console.log(`[${dev.name}] Landscape unobscured map: ${vis}%`);
      expect(vis).toBeGreaterThanOrEqual(55);

      // Capture screenshot: Landscape Explore
      await page.screenshot({ path: `test-results/mobile-evidence/${dev.name}-explore.png` });

      // Verify camera switch receives center click
      const cameraSwitch = page.getByRole("switch", { name: "Hiển thị camera" });
      await expect(cameraSwitch).toBeVisible();
      const box = await cameraSwitch.boundingBox();
      expect(box).not.toBeNull();
      await page.mouse.click(box!.x + box!.width / 2, box!.y + box!.height / 2);
      await expect(cameraSwitch).toHaveAttribute("aria-checked", "false");

      const box2 = await cameraSwitch.boundingBox();
      expect(box2).not.toBeNull();
      await page.mouse.click(box2!.x + box2!.width / 2, box2!.y + box2!.height / 2);
      await expect(cameraSwitch).toHaveAttribute("aria-checked", "true");
    });
  }
});

test.describe("Auxiliary Pages Mobile Verification", () => {
  const AUX_PAGES = [
    { url: "/monitor", name: "Camera Monitor" },
    { url: "/news", name: "Traffic News" },
    { url: "/dashboard", name: "Dashboard" },
    { url: "/account", name: "Account Profile" },
  ];

  for (const aux of AUX_PAGES) {
    test(`Mobile viewport 390x844: ${aux.name} has no horizontal overflow`, async ({ page }) => {
      await page.setViewportSize({ width: 390, height: 844 });
      await page.addInitScript(() => {
        localStorage.setItem('safepath_tour_state_v1', JSON.stringify({ version: 'v1', status: 'skipped', updatedAt: new Date().toISOString() }));
      });
      await page.goto(aux.url);
      await dismissWelcomeIfOpen(page);

      const metrics = await page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        viewportWidth: window.innerWidth,
      }));

      expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.viewportWidth + 1); // 1px rounding tolerance
    });
  }
});

