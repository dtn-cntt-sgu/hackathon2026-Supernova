import { test, expect } from "@playwright/test";

// Phase 1 (P0) — Free Search, Current Location, and Navigation State Live E2E Suite.
// Strictly adheres to Zero-Mock: All routing calls go to live OSRM; places come from live geocoder.

test.describe("Phase 1 Geocoding & Place Search Live", () => {
  test("user types 3 real addresses NOT in presets, selects suggestion, and routes live on OSRM", async ({
    page,
  }) => {
    test.setTimeout(60000);
    await page.goto("/map");

    // 1. First query: "Nguyễn Huệ" (Street in District 1, not in HCMC_PRESETS)
    const originInput = page.getByRole("combobox", { name: "Từ đâu? Điểm xuất phát" });
    await originInput.fill("Nguyễn Huệ");
    await page.waitForTimeout(400);

    // Verify suggestions listbox appears with real Photon/OSM results
    const option1 = page.getByRole("option").first();
    await expect(option1).toBeVisible({ timeout: 6000 });
    await option1.click();
    await expect(page.getByRole("listbox")).toHaveCount(0);

    // 2. Second query: "Điện Biên Phủ" (Major arterial road in Bình Thạnh/Q3)
    const destInput = page.getByRole("combobox", { name: "Đến đâu? Điểm đến" });
    await destInput.fill("Điện Biên Phủ");
    await page.waitForTimeout(400);

    const option2 = page.getByRole("option").first();
    await expect(option2).toBeVisible({ timeout: 6000 });
    await option2.click();
    await expect(page.getByRole("listbox")).toHaveCount(0);

    // 3. Trigger live OSRM search
    const searchBtn = page.getByRole("button", { name: /^Tìm tuyến đường/ });
    await expect(searchBtn).toBeEnabled();
    await searchBtn.click();

    // Verify live route response
    await expect(page.getByText("Tuyến đang chọn")).toBeVisible({ timeout: 15000 });
    await expect(page.locator("[data-route-vertices]")).toHaveAttribute(
      "data-route-vertices",
      /^\d{2,}$/
    );

    // 4. Third query: Change destination to "Võ Văn Kiệt" (Riverside expressway)
    await destInput.fill("Võ Văn Kiệt");
    await page.waitForTimeout(400);
    const option3 = page.getByRole("option").first();
    await expect(option3).toBeVisible({ timeout: 6000 });
    await option3.click();

    await searchBtn.click();
    await expect(page.getByText("Tuyến đang chọn")).toBeVisible({ timeout: 15000 });
    await expect(page.locator("[data-route-vertices]")).toHaveAttribute(
      "data-route-vertices",
      /^\d{2,}$/
    );

    await page.screenshot({ path: "test-results/phase1-custom-address-route.png", fullPage: true });
  });

  test("direct coordinate input parsing (lat, lng)", async ({ page }) => {
    await page.goto("/map");

    const originInput = page.getByRole("combobox", { name: "Từ đâu? Điểm xuất phát" });
    await originInput.fill("10.7725, 106.6980");
    await page.waitForTimeout(300);

    const option = page.getByRole("option").first();
    await expect(option).toBeVisible({ timeout: 4000 });
    await expect(option).toContainText("Tọa độ: 10.77250, 106.69800");
    await option.click();

    // Verify coordinate badge is locked in
    await expect(page.getByText("10.77250, 106.69800")).toBeVisible();
  });

  test("short query (< 3 chars) does not trigger provider suggestions", async ({ page }) => {
    await page.goto("/map");

    const originInput = page.getByRole("combobox", { name: "Từ đâu? Điểm xuất phát" });
    await originInput.fill("sg");
    await page.waitForTimeout(400);

    // Option should not contain external results
    const option = page.getByRole("option");
    await expect(option).toHaveCount(0);
  });

  test("search button is disabled when origin or destination is cleared", async ({ page }) => {
    await page.goto("/map");

    // Clear origin input
    const clearOriginBtn = page.locator("[data-testid='origin-combobox'] button[aria-label='Xóa nội dung']");
    if (await clearOriginBtn.count()) {
      await clearOriginBtn.click();
    } else {
      const originInput = page.getByRole("combobox", { name: "Từ đâu? Điểm xuất phát" });
      await originInput.fill("");
    }

    const searchBtn = page.getByRole("button", { name: /Vui lòng chọn Điểm đi và Điểm đến/ });
    await expect(searchBtn).toBeDisabled();
  });

  test("browser geolocation success grants position and renders location marker", async ({
    context,
    page,
  }) => {
    // Stub browser geolocation permission and coordinates for Ho Chi Minh City center
    await context.grantPermissions(["geolocation"]);
    await context.setGeolocation({
      latitude: 10.7769,
      longitude: 106.7009,
      accuracy: 25,
    });

    await page.goto("/map");

    // Click "Vị trí của tôi" button
    const locateBtn = page.getByRole("button", { name: "Vị trí của tôi" }).first();
    await expect(locateBtn).toBeVisible();
    await locateBtn.click();

    // Verify origin input reflects current position
    const originInput = page.getByRole("combobox", { name: "Từ đâu? Điểm xuất phát" });
    await expect(originInput).toHaveValue(/Vị trí của bạn/);

    // Verify current location marker rendered on map
    await expect(
      page.locator("[data-marker-type='current-location']")
    ).toBeVisible({ timeout: 8000 });

    await page.screenshot({ path: "test-results/phase1-geolocation-active.png", fullPage: true });
  });

  test("browser geolocation denied displays clear non-blocking error", async ({
    context,
    page,
  }) => {
    // Clear permissions to simulate user denying location access
    await context.clearPermissions();

    await page.goto("/map");

    const locateBtn = page.getByRole("button", { name: "Vị trí của tôi" }).first();
    await expect(locateBtn).toBeVisible();
    await locateBtn.click();

    // Verify error notification is displayed to user
    await expect(
      page.getByText(/Bạn đã từ chối cấp quyền vị trí|Lỗi định vị/)
    ).toBeVisible({ timeout: 5000 });
  });
});
