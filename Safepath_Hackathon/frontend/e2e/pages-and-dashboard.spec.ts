import { test, expect } from "@playwright/test";

test.describe("Phase 8F & 8G: Multi-page Dashboard, Monitor & Account Suite", () => {
  test("Navbar links navigate to Monitor, Dashboard, and Account pages", async ({ page }) => {
    await page.goto("/map");

    // Check navbar brand and links
    await expect(page.locator("header")).toBeVisible();
    await expect(page.locator("text=SafePath")).toBeVisible();

    // Navigate to Camera Monitor page
    const monitorLink = page.locator("a[href='/monitor']").first();
    await expect(monitorLink).toBeVisible();
    await monitorLink.click();

    // Verify Monitor page loaded
    await page.waitForURL("**/monitor");
    await expect(page.locator("text=Trung tâm Giám sát Camera")).toBeVisible();
    await expect(page.locator("text=Quan trắc hình ảnh thời gian thực")).toBeVisible();

    // Navigate to Community Dashboard page
    const dashboardLink = page.locator("a[href='/dashboard']").first();
    await expect(dashboardLink).toBeVisible();
    await dashboardLink.click();

    // Verify Dashboard page loaded
    await page.waitForURL("**/dashboard");
    await expect(page.locator("text=Bảng điều khiển")).toBeVisible();
    await expect(page.locator("text=Hành trình thường nhật của tôi")).toBeVisible();
    await expect(page.getByText("Lịch sử tìm đường", { exact: true })).toBeVisible();

    // Navigate to Account / Settings page
    const accountLink = page.locator("a[href='/account']").first();
    await expect(accountLink).toBeVisible();
    await accountLink.click();

    // Verify Account page loaded
    await page.waitForURL("**/account");
    await expect(page.locator("text=Tài khoản & Cài đặt")).toBeVisible();
    await expect(page.locator("text=Phương tiện di chuyển chính")).toBeVisible();

    // Return to Map
    const mapLink = page.locator("a[href='/map']").first();
    await expect(mapLink).toBeVisible();
    await mapLink.click();
    await page.waitForURL("**/map");
    await expect(page.locator("[data-testid='route-map']")).toBeVisible();
  });

  test("Camera Monitor page lists real cameras, filters by district and search", async ({ page }) => {
    await page.goto("/monitor");

    // Wait for cameras to finish loading from API
    const cameraGrid = page.locator("[data-testid='camera-monitor-grid']");
    await expect(cameraGrid).toBeVisible({ timeout: 15000 });

    // Search camera input
    const searchInput = page.locator("input[placeholder*='Tìm camera theo tên']");
    await expect(searchInput).toBeVisible();
    await searchInput.fill("Nguyễn Hữu Cảnh");

    // Check filtered camera cards
    const filteredCards = cameraGrid.locator("> div");
    await expect(filteredCards.first()).toBeVisible({ timeout: 10000 });
    const count = await filteredCards.count();
    expect(count).toBeGreaterThan(0);

    // Clicking camera card opens modal
    const firstCard = filteredCards.first();
    await firstCard.click();
    await expect(page.locator("[data-testid='camera-evidence-modal']")).toBeVisible();

    // Close modal
    const closeBtn = page.locator("button[aria-label='Đóng chi tiết camera']");
    await closeBtn.click();
    await expect(page.locator("[data-testid='camera-evidence-modal']")).not.toBeVisible();
  });

  test("Guest profile does not invent saved places or report submission", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page.getByText(/Chưa có địa điểm đã lưu/)).toBeVisible();
    await expect(page.getByText(/Chưa có lịch sử tìm đường/)).toBeVisible();
    await expect(page.getByText("Chế độ Khách bảo mật")).toBeVisible();
  });

  test("Account page allows vehicle switching and shows OAuth configuration state", async ({ page }) => {
    await page.goto("/account");

    // Check vehicle selector cards
    const carOption = page.locator("text=Ô tô (4 bánh)");
    await expect(carOption).toBeVisible();
    await carOption.click();

    // Check feedback toast
    await expect(page.locator("text=Vui lòng đăng nhập để lưu phương tiện")).toBeVisible();

    // Check Google login section
    const googleBtn = page.locator("button:has-text('Tiếp tục với Google')");
    await expect(googleBtn).toBeVisible();
  });
});

