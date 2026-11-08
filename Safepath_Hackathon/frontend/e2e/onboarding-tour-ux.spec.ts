import { test, expect } from "@playwright/test";

test.describe("Onboarding Tour UI/UX Fix & Liquid Glass Polish", () => {
  test.beforeEach(async ({ page, context }) => {
    await context.clearCookies();
    await page.addInitScript(() => {
      if (!sessionStorage.getItem("__sp_tour_init")) {
        localStorage.clear();
        sessionStorage.setItem("__sp_tour_init", "1");
      }
    });
  });

  test("1. /news tour Step 4 spotlights ONLY the bookmark button without global blur", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/news");

    // Welcome dialog appears on first visit
    const welcomeDialog = page.locator("[role='dialog'][aria-labelledby='onboarding-welcome-title']");
    await expect(welcomeDialog).toBeVisible({ timeout: 10000 });

    // Verify welcome modal backdrop does not have heavy blur
    const welcomeBackdrop = welcomeDialog;
    const welcomeBackdropFilter = await welcomeBackdrop.evaluate((el) => {
      return window.getComputedStyle(el).backdropFilter || (el as any).style?.backdropFilter || "";
    });
    expect(welcomeBackdropFilter).not.toContain("blur(20px)");

    // Start news tour
    const startBtn = welcomeDialog.getByRole("button", { name: "Bắt đầu hướng dẫn" });
    await startBtn.click();

    const driverPopover = page.locator(".driver-popover");
    await expect(driverPopover).toBeVisible({ timeout: 6000 });

    // Step 1: news-hero
    await expect(driverPopover.locator(".driver-popover-title")).toContainText("Tiêu điểm giao thông");
    await expect(driverPopover.locator(".driver-popover-progress-text")).toContainText("1 / 4");

    // Click Next -> Step 2: news-highlights
    const nextBtn = driverPopover.locator(".driver-popover-next-btn");
    await nextBtn.click();
    await expect(driverPopover.locator(".driver-popover-title")).toContainText("Tình hình đáng chú ý");
    await expect(driverPopover.locator(".driver-popover-progress-text")).toContainText("2 / 4");

    // Click Next -> Step 3: news-filters
    await nextBtn.click();
    await expect(driverPopover.locator(".driver-popover-title")).toContainText("Bộ lọc sự cố");
    await expect(driverPopover.locator(".driver-popover-progress-text")).toContainText("3 / 4");

    // Verify Skip ("Bỏ qua") button exists in popover footer on step 3
    const skipBtnStep3 = driverPopover.locator(".driver-popover-skip-btn");
    await expect(skipBtnStep3).toBeVisible();
    await expect(skipBtnStep3).toHaveText("Bỏ qua");

    // Click Next -> Step 4: Bookmark Action
    await nextBtn.click();

    // Verify Step 4 Title and Description
    await expect(driverPopover.locator(".driver-popover-title")).toContainText("Lưu tin tức quan trọng");
    await expect(driverPopover.locator(".driver-popover-description")).toContainText(
      "Bấm biểu tượng dấu trang bên cạnh bài viết để lưu tin bạn quan tâm"
    );
    await expect(driverPopover.locator(".driver-popover-progress-text")).toContainText("4 / 4");

    // 1. Verify Spotlight dimensions: Must tightly outline the Bookmark button, NOT the entire news list!
    const activeEl = page.locator(".driver-active-element");
    await expect(activeEl).toBeVisible();
    const activeBox = await activeEl.boundingBox();
    expect(activeBox).not.toBeNull();
    if (activeBox) {
      // Bookmark button is ~32x32px -> spotlight element is around 32-44px.
      // Crucially, it must be well under 120px, proving it does not outline the entire 800px+ news container!
      expect(activeBox.width).toBeLessThan(120);
      expect(activeBox.height).toBeLessThan(120);
    }

    // 2. Verify NO global blur on driver-overlay
    const driverOverlay = page.locator(".driver-overlay");
    const overlayBackdropFilter = await driverOverlay.evaluate((el) => {
      const style = window.getComputedStyle(el);
      return style.backdropFilter || style.getPropertyValue("-webkit-backdrop-filter") || "none";
    });
    expect(overlayBackdropFilter).toBe("none");

    // 3. Verify target Bookmark button is crisp, elevated and visible
    const targetBookmark = page.locator("[data-tour='news-bookmark-action']");
    await expect(targetBookmark).toBeVisible();

    // Capture crisp screenshot of Step 4 Bookmark spotlight
    await page.screenshot({ path: "docs/news_tour_step4_bookmark_spotlight.png" });

    // 4. Test "Quay lại" button: goes back to Step 3
    const prevBtn = driverPopover.locator(".driver-popover-prev-btn");
    await prevBtn.click();
    await expect(driverPopover.locator(".driver-popover-title")).toContainText("Bộ lọc sự cố");
    await expect(driverPopover.locator(".driver-popover-progress-text")).toContainText("3 / 4");

    // Return to Step 4
    await nextBtn.click();
    await expect(driverPopover.locator(".driver-popover-title")).toContainText("Lưu tin tức quan trọng");

    // 5. Test "Hoàn tất" button: dismisses tour and sets status=completed
    const doneBtn = driverPopover.locator(".driver-popover-done-btn, .driver-popover-next-btn");
    await doneBtn.click();
    await expect(driverPopover).not.toBeVisible({ timeout: 5000 });

    const tourState = await page.evaluate(() => localStorage.getItem("safepath_tour_state_v1"));
    expect(JSON.parse(tourState || "{}").status).toBe("completed");

    // 6. Refresh page: does not auto-open welcome modal when completed
    await page.reload();
    await page.waitForTimeout(1000);
    await expect(welcomeDialog).not.toBeVisible();
  });

  test("2. Skip button in popover dismisses tour and persists skipped status", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/news");

    const welcomeDialog = page.locator("[role='dialog'][aria-labelledby='onboarding-welcome-title']");
    await expect(welcomeDialog).toBeVisible({ timeout: 10000 });
    await welcomeDialog.getByRole("button", { name: "Bắt đầu hướng dẫn" }).click();

    const driverPopover = page.locator(".driver-popover");
    await expect(driverPopover).toBeVisible({ timeout: 5000 });

    // Click Skip ("Bỏ qua") on step 1
    const skipBtn = driverPopover.locator(".driver-popover-skip-btn");
    await expect(skipBtn).toBeVisible();
    await skipBtn.click();

    // Tour is dismissed
    await expect(driverPopover).not.toBeVisible({ timeout: 5000 });

    // Status is "skipped"
    const tourState = await page.evaluate(() => localStorage.getItem("safepath_tour_state_v1"));
    expect(JSON.parse(tourState || "{}").status).toBe("skipped");

    // Reload does not reopen
    await page.reload();
    await page.waitForTimeout(1000);
    await expect(welcomeDialog).not.toBeVisible();
  });

  test("3. Onboarding Help button in header re-opens tour on demand", async ({ page }) => {
    // Set tour already completed in localStorage
    await page.addInitScript(() => {
      localStorage.setItem(
        "safepath_tour_state_v1",
        JSON.stringify({ version: "v1", status: "completed", updatedAt: new Date().toISOString() })
      );
    });

    await page.goto("/news");

    // Welcome dialog should NOT show
    const welcomeDialog = page.locator("[role='dialog'][aria-labelledby='onboarding-welcome-title']");
    await expect(welcomeDialog).not.toBeVisible();

    // Click "Hướng dẫn sử dụng" help button in header
    const helpBtn = page.locator("button[aria-label='Hướng dẫn sử dụng']").first();
    await expect(helpBtn).toBeVisible();
    await helpBtn.click();

    // Driver popover launches directly into step 1
    const driverPopover = page.locator(".driver-popover");
    await expect(driverPopover).toBeVisible({ timeout: 5000 });
    await expect(driverPopover.locator(".driver-popover-title")).toContainText("Tiêu điểm giao thông");
  });

  test("4. Responsive layout on Tablet (768px) and Mobile (390px)", async ({ page }) => {
    // 1. Tablet 768px
    await page.setViewportSize({ width: 768, height: 1024 });
    await page.goto("/news");

    const welcomeDialog = page.locator("[role='dialog'][aria-labelledby='onboarding-welcome-title']");
    await expect(welcomeDialog).toBeVisible({ timeout: 10000 });
    await welcomeDialog.getByRole("button", { name: "Bắt đầu hướng dẫn" }).click();

    const driverPopover = page.locator(".driver-popover");
    await expect(driverPopover).toBeVisible({ timeout: 5000 });

    let popoverBox = await driverPopover.boundingBox();
    expect(popoverBox).not.toBeNull();
    if (popoverBox) {
      expect(popoverBox.x).toBeGreaterThanOrEqual(0);
      expect(popoverBox.x + popoverBox.width).toBeLessThanOrEqual(768 + 10);
    }

    // Advance to step 4 on tablet
    const nextBtn = driverPopover.locator(".driver-popover-next-btn");
    await nextBtn.click(); // step 2
    await nextBtn.click(); // step 3
    await nextBtn.click(); // step 4: bookmark

    await expect(driverPopover.locator(".driver-popover-title")).toContainText("Lưu tin tức quan trọng");
    popoverBox = await driverPopover.boundingBox();
    if (popoverBox) {
      expect(popoverBox.x).toBeGreaterThanOrEqual(0);
      expect(popoverBox.x + popoverBox.width).toBeLessThanOrEqual(768 + 10);
    }

    // 2. Mobile 390px (iPhone 14 / modern mobile)
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/news");

    const helpBtn = page.locator("button[aria-label='Hướng dẫn sử dụng']").first();
    await expect(helpBtn).toBeVisible({ timeout: 10000 });
    await helpBtn.click();

    await expect(driverPopover).toBeVisible({ timeout: 5000 });
    const mobileBox = await driverPopover.boundingBox();
    expect(mobileBox).not.toBeNull();
    if (mobileBox) {
      expect(mobileBox.width).toBeLessThanOrEqual(390);
    }

    // Capture mobile tour screenshot
    await page.screenshot({ path: "docs/onboarding_tour_mobile_crisp.png" });
  });

  test("5. Actual bookmark click functionality is completely preserved", async ({ page }) => {
    await page.goto("/news");

    // Dismiss welcome dialog
    const welcomeDialog = page.locator("[role='dialog'][aria-labelledby='onboarding-welcome-title']");
    await expect(welcomeDialog).toBeVisible({ timeout: 10000 });
    await welcomeDialog.getByRole("button", { name: "Bỏ qua" }).click();

    // Click actual bookmark button on first article
    const bookmarkBtn = page.locator("[data-tour='news-bookmark-action']");
    await expect(bookmarkBtn).toBeVisible({ timeout: 10000 });
    await bookmarkBtn.click();

    // Check localStorage saved news contains the article id
    const saved = await page.evaluate(() => localStorage.getItem("safepath_saved_news"));
    expect(saved).not.toBeNull();
    const savedArr = JSON.parse(saved || "[]");
    expect(savedArr.length).toBeGreaterThan(0);

    // Click again to unbookmark
    await bookmarkBtn.click();
    const unSaved = await page.evaluate(() => localStorage.getItem("safepath_saved_news"));
    const unSavedArr = JSON.parse(unSaved || "[]");
    expect(unSavedArr.length).toBe(0);
  });
});
