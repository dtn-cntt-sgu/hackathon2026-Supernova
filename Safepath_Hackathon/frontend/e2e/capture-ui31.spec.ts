import { test, expect } from "@playwright/test";
import path from "path";

test.describe("UI 3.1 Pearl Aurora Screenshots Acceptance", () => {
  test("capture all 8 UI 3.1 acceptance screenshots", async ({ browser }) => {
    test.setTimeout(90000);

    // 1. Desktop context (1440x900)
    const desktopContext = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      deviceScaleFactor: 2,
    });
    const desktopPage = await desktopContext.newPage();

    // 1.1 /map desktop overview
    console.log("Capturing 1: docs/post_ui31_map_desktop.png");
    await desktopPage.goto("/map", { waitUntil: "networkidle" });
    await desktopPage.waitForTimeout(2500);
    await desktopPage.screenshot({ path: path.resolve("../docs/post_ui31_map_desktop.png") });

    // 1.2 /map sidebar focused
    console.log("Capturing 2: docs/post_ui31_map_sidebar.png");
    const searchInput = desktopPage.locator('input[placeholder*="Tìm địa điểm"], input[placeholder*="điểm đến"]').first();
    if (await searchInput.isVisible()) {
      await searchInput.click();
      await searchInput.fill("Bến Thành");
      await desktopPage.waitForTimeout(1000);
    }
    await desktopPage.screenshot({ path: path.resolve("../docs/post_ui31_map_sidebar.png") });

    // 1.3 /map hover interactive state
    console.log("Capturing 3: docs/post_ui31_map_hover.png");
    const searchBtn = desktopPage.locator('button:has-text("Tìm đường"), button:has-text("Dẫn đường")').first();
    if (await searchBtn.isVisible()) {
      await searchBtn.hover();
      await desktopPage.waitForTimeout(500);
    }
    await desktopPage.screenshot({ path: path.resolve("../docs/post_ui31_map_hover.png") });

    // 1.4 /map with route and camera markers
    console.log("Capturing 4: docs/post_ui31_map_route.png");
    const presetBtn = desktopPage.locator('button:has-text("Chợ Bến Thành"), button:has-text("Bến Thành")').first();
    if (await presetBtn.isVisible()) {
      await presetBtn.click();
      await desktopPage.waitForTimeout(1000);
    }
    const endPresetBtn = desktopPage.locator('button:has-text("Ngã tư Hàng Xanh"), button:has-text("Hàng Xanh")').first();
    if (await endPresetBtn.isVisible()) {
      await endPresetBtn.click();
      await desktopPage.waitForTimeout(1000);
    }
    const routeSubmitBtn = desktopPage.locator('button:has-text("Tìm đường"), button:has-text("Dẫn đường")').first();
    if (await routeSubmitBtn.isVisible()) {
      await routeSubmitBtn.click();
      await desktopPage.waitForTimeout(3000);
    }
    await desktopPage.screenshot({ path: path.resolve("../docs/post_ui31_map_route.png") });

    // 1.5 /monitor desktop gallery
    console.log("Capturing 5: docs/post_ui31_monitor_desktop.png");
    await desktopPage.goto("/monitor", { waitUntil: "networkidle" });
    await desktopPage.waitForTimeout(2500);
    await desktopPage.screenshot({ path: path.resolve("../docs/post_ui31_monitor_desktop.png") });

    // 1.6 /monitor hover on camera card
    console.log("Capturing 6: docs/post_ui31_monitor_hover.png");
    const cameraCard = desktopPage.locator('[data-testid^="camera-card-"], article').first();
    if (await cameraCard.isVisible()) {
      await cameraCard.hover();
      await desktopPage.waitForTimeout(600);
    }
    await desktopPage.screenshot({ path: path.resolve("../docs/post_ui31_monitor_hover.png") });

    // 1.7 /monitor modal opened
    console.log("Capturing 7: docs/post_ui31_monitor_modal.png");
    if (await cameraCard.isVisible()) {
      await cameraCard.click();
      await desktopPage.waitForSelector('[data-testid="camera-evidence-modal"]', { timeout: 6000 }).catch(() => {});
      await desktopPage.waitForTimeout(1500);
    }
    await desktopPage.screenshot({ path: path.resolve("../docs/post_ui31_monitor_modal.png") });

    await desktopContext.close();

    // 2. Mobile Context (390x844)
    console.log("Capturing Mobile Context...");
    const mobileContext = await browser.newContext({
      viewport: { width: 390, height: 844 },
      deviceScaleFactor: 3,
      isMobile: true,
      hasTouch: true,
    });
    const mobilePage = await mobileContext.newPage();

    // 2.1 /map mobile
    console.log("Capturing 8a: docs/post_ui31_mobile_map.png");
    await mobilePage.goto("/map", { waitUntil: "networkidle" });
    await mobilePage.waitForTimeout(2500);
    await mobilePage.screenshot({ path: path.resolve("../docs/post_ui31_mobile_map.png") });

    // 2.2 /monitor mobile
    console.log("Capturing 8b: docs/post_ui31_mobile_monitor.png");
    await mobilePage.goto("/monitor", { waitUntil: "networkidle" });
    await mobilePage.waitForTimeout(2500);
    await mobilePage.screenshot({ path: path.resolve("../docs/post_ui31_mobile_monitor.png") });

    await mobileContext.close();
    console.log("All 8 acceptance screenshots generated successfully!");
  });
});

