import { test, expect } from "@playwright/test";

test.describe("Phase 11: Daily Traffic News Center & Driver.js Interactive Onboarding", () => {
  test.beforeEach(async ({ page, context }) => {
    // Clear cookies and initialize fresh localStorage per test session without wiping on reload
    await context.clearCookies();
    await page.addInitScript(() => {
      if (!sessionStorage.getItem("__sp_test_init")) {
        localStorage.clear();
        sessionStorage.setItem("__sp_test_init", "1");
      }
    });
  });

  test("1. Traffic News Center renders real articles, filters, search, and bookmarks on desktop", async ({
    page,
  }) => {
    await page.goto("/news");

    // Header & Brand
    await expect(page.locator("h1")).toContainText("Bản tin giao thông TP.HCM");
    await expect(page.getByText("Những thông tin giao thông đáng chú ý")).toBeVisible();

    // Data verification: Real articles must load from backend API
    const newsCards = page.locator("article");
    await expect(newsCards.first()).toBeVisible({ timeout: 15000 });
    const count = await newsCards.count();
    expect(count).toBeGreaterThan(0);

    // Verify at least one article has title, summary, source
    const firstTitle = await newsCards.first().locator("h4 a").innerText();
    expect(firstTitle.length).toBeGreaterThan(5);

    // Check external link has valid href (http/https)
    const extLink = await newsCards.first().locator("a[target='_blank']").first().getAttribute("href");
    expect(extLink).toMatch(/^https?:\/\//);

    // Test Category filter pill
    const allTab = page.locator("button:has-text('Tất cả')").first();
    await expect(allTab).toBeVisible();

    // Bookmark toggle test
    const bookmarkBtn = newsCards.first().locator("button[title*='Lưu'], button[title*='lưu'], button:has(svg.lucide-bookmark)").first();
    await bookmarkBtn.click();
    // Verify stored in localStorage
    const saved = await page.evaluate(() => localStorage.getItem("safepath_saved_news"));
    expect(saved).not.toBeNull();
    expect(JSON.parse(saved || "[]").length).toBeGreaterThan(0);

    // Weather & Tide sidebar
    await expect(page.getByText("Thời tiết & Thủy văn thực tế")).toBeVisible();
    await expect(page.getByText("Nguồn dữ liệu bản tin")).toBeVisible();

    // Capture desktop screenshot
    await page.screenshot({ path: "docs/news_page_desktop.png", fullPage: false });
  });

  test("2. Traffic News Center is fully responsive on mobile without horizontal overflow", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto("/news");

    await expect(page.locator("h1")).toBeVisible({ timeout: 15000 });
    await expect(page.locator("article").first()).toBeVisible({ timeout: 15000 });

    // Check no horizontal overflow
    const hasHorizontalOverflow = await page.evaluate(() => {
      return document.documentElement.scrollWidth > window.innerWidth;
    });
    expect(hasHorizontalOverflow).toBe(false);

    // Capture mobile screenshot
    await page.screenshot({ path: "docs/news_page_mobile.png" });
  });

  test("3. Landing Scene 02 is updated to Daily Traffic News experience", async ({ page }) => {
    await page.goto("/");

    // Verify navbar link
    const newsNavLink = page.locator(".nav-links a[href='/news']");
    await expect(newsNavLink).toBeVisible();

    // Verify Scene 02 Heading
    const scene02Eyebrow = page.getByText("02 / BẢN TIN GIAO THÔNG THÀNH PHỐ");
    await expect(scene02Eyebrow).toBeAttached();

    const scene02Headline = page.getByText("Biết trước những gì đang diễn ra.");
    await expect(scene02Headline).toBeAttached();

    const scene02Subheadline = page.getByText("Cập nhật giao thông trước mỗi hành trình.");
    await expect(scene02Subheadline).toBeAttached();

    // Verify CTA button to /news
    const ctaButton = page.locator("a[href='/news']:has-text('Khám phá bản tin giao thông')");
    await expect(ctaButton).toBeAttached();

    // Scroll to Scene 02
    await page.evaluate(() => {
      const el = document.querySelector(".story-scene.fusion-scene");
      if (el) el.scrollIntoView();
    });
    await page.waitForTimeout(600);

    // Capture Scene 02 screenshot
    await page.screenshot({ path: "docs/landing_scene02_news.png" });
  });

  test("4. Driver.js interactive onboarding: Welcome dialog and 6 spotlight steps on /map", async ({
    page,
  }) => {
    // Navigate as new guest
    await page.goto("/map");

    // 1. Welcome dialog appears automatically
    const welcomeDialog = page.locator("[role='dialog'][aria-labelledby='onboarding-welcome-title']");
    await expect(welcomeDialog).toBeVisible({ timeout: 8000 });
    await expect(welcomeDialog).toContainText("Chào mừng bạn đến SafePathAI!");

    // Capture welcome dialog screenshot
    await page.screenshot({ path: "docs/onboarding_welcome_dialog.png" });

    // 2. Start tour
    const startBtn = welcomeDialog.getByRole("button", { name: "Bắt đầu hướng dẫn" });
    await startBtn.click();

    // 3. Driver.js popover appears
    const driverPopover = page.locator(".driver-popover");
    await expect(driverPopover).toBeVisible({ timeout: 5000 });

    // Step 1: Origin input
    await expect(driverPopover.locator(".driver-popover-title")).toContainText("Bước 1: Chọn điểm xuất phát");
    await expect(driverPopover.locator(".driver-popover-progress-text")).toContainText(/1\s*(\/|of)/);

    // Click Next -> Step 2: Destination input
    const nextBtn = driverPopover.locator(".driver-popover-next-btn");
    await nextBtn.click();

    await expect(driverPopover.locator(".driver-popover-title")).toContainText("Bước 2: Chọn điểm đến");
    await expect(driverPopover.locator(".driver-popover-progress-text")).toContainText(/2\s*(\/|of)/);

    // Capture Step 2 destination spotlight screenshot
    await page.screenshot({ path: "docs/onboarding_spotlight_destination.png" });

    // Step 3: Search button
    await nextBtn.click();
    await expect(driverPopover.locator(".driver-popover-title")).toContainText("Bước 3: Tìm tuyến đường");

    // Step 4: Camera toggle
    await nextBtn.click();
    await expect(driverPopover.locator(".driver-popover-title")).toContainText("Bước 4: Camera giao thông");

    // Capture Step 4 camera toggle screenshot
    await page.screenshot({ path: "docs/onboarding_spotlight_camera_toggle.png" });

    // Step 5: Guidance
    await nextBtn.click();
    await expect(driverPopover.locator(".driver-popover-title")).toContainText("Bước 5: Hướng dẫn di chuyển");

    // Step 6: Traffic news link
    await nextBtn.click();
    await expect(driverPopover.locator(".driver-popover-title")).toContainText("Bước 6: Bản tin giao thông");

    // Click Done button
    const doneBtn = driverPopover.locator(".driver-popover-next-btn, .driver-popover-done-btn");
    await doneBtn.click();

    // Verify driver popover is dismissed
    await expect(driverPopover).not.toBeVisible({ timeout: 5000 });

    // Verify completion stored in localStorage
    const tourState = await page.evaluate(() => localStorage.getItem("safepath_tour_state_v1"));
    expect(tourState).not.toBeNull();
    expect(JSON.parse(tourState || "{}").status).toBe("completed");
  });

  test("5. Onboarding skip, no repeated intrusion, and re-opening from Help button", async ({
    page,
  }) => {
    await page.goto("/map");

    // Welcome dialog appears
    const welcomeDialog = page.locator("[role='dialog'][aria-labelledby='onboarding-welcome-title']");
    await expect(welcomeDialog).toBeVisible({ timeout: 8000 });

    // Click Skip button
    const skipBtn = welcomeDialog.getByRole("button", { name: "Bỏ qua" });
    await skipBtn.click();

    await expect(welcomeDialog).not.toBeVisible();

    // Verify status is "skipped" in localStorage
    const tourState = await page.evaluate(() => localStorage.getItem("safepath_tour_state_v1"));
    expect(JSON.parse(tourState || "{}").status).toBe("skipped");

    // Refresh page: Welcome dialog should NOT reappear
    await page.reload();
    await page.waitForTimeout(1500);
    await expect(welcomeDialog).not.toBeVisible();

    // Capture completed/skipped state screenshot
    await page.screenshot({ path: "docs/onboarding_completed_state.png" });

    // Reopen tour on-demand from "Hướng dẫn sử dụng" help button in header
    const helpBtn = page.locator("button[aria-label='Hướng dẫn sử dụng']").first();
    await expect(helpBtn).toBeVisible();
    await helpBtn.click();

    // Driver popover launches immediately
    const driverPopover = page.locator(".driver-popover");
    await expect(driverPopover).toBeVisible({ timeout: 5000 });
    await expect(driverPopover.locator(".driver-popover-title")).toContainText("Bước 1: Chọn điểm xuất phát");
  });

  test("6. Onboarding tour on mobile adapts correctly to small screens", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto("/map");

    const welcomeDialog = page.locator("[role='dialog'][aria-labelledby='onboarding-welcome-title']");
    await expect(welcomeDialog).toBeVisible({ timeout: 8000 });

    // Start tour on mobile
    const startBtn = welcomeDialog.getByRole("button", { name: "Bắt đầu hướng dẫn" });
    await startBtn.click();

    const driverPopover = page.locator(".driver-popover");
    await expect(driverPopover).toBeVisible({ timeout: 5000 });

    // Check popover width does not exceed viewport
    const popoverBox = await driverPopover.boundingBox();
    expect(popoverBox).not.toBeNull();
    if (popoverBox) {
      expect(popoverBox.width).toBeLessThanOrEqual(375);
    }

    // Capture mobile tour screenshot
    await page.screenshot({ path: "docs/onboarding_tour_mobile.png" });
  });
});
