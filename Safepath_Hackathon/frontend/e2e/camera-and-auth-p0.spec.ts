import { test, expect } from "@playwright/test";

test.describe("P0 Production Recovery: Camera Ingestion, MapLibre Rendering & Auth", () => {
  test("1. MapLibre camera rendering, toggle reliability, and filter switching", async ({ page }) => {
    await page.goto("/map");

    // Map container exists
    const mapContainer = page.locator("[data-testid='route-map']");
    await expect(mapContainer).toBeVisible();
    await expect(page.locator(".maplibregl-canvas")).toBeVisible({ timeout: 15000 });

    // Camera toggle switch is visible and ON by default
    const cameraSwitch = page.getByRole("switch", { name: "Hiển thị camera" });
    await expect(cameraSwitch).toBeVisible();
    await expect(cameraSwitch).toHaveAttribute("aria-checked", "true");

    // Camera features populated (> 0)
    await expect(mapContainer).toHaveAttribute("data-camera-feature-count", /^[1-9]\d*$/, { timeout: 10000 });
    const initialCount = parseInt((await mapContainer.getAttribute("data-camera-feature-count")) || "0", 10);
    expect(initialCount).toBeGreaterThan(0);

    // Toggle OFF -> immediately 0
    await cameraSwitch.click();
    await expect(cameraSwitch).toHaveAttribute("aria-checked", "false");
    await expect(mapContainer).toHaveAttribute("data-camera-feature-count", "0");

    // Toggle ON -> immediately restored
    await cameraSwitch.click();
    await expect(cameraSwitch).toHaveAttribute("aria-checked", "true");
    await expect(mapContainer).toHaveAttribute("data-camera-feature-count", /^[1-9]\d*$/);

    // Open filter dropdown
    const filterBtn = page.getByRole("button", { name: "Lọc loại camera" });
    await expect(filterBtn).toBeVisible();
    await filterBtn.click();

    // Select 'Trên lộ trình' without a searched route
    const onRouteOption = page.locator("button:has-text('Trên lộ trình')");
    await expect(onRouteOption).toBeVisible();
    await onRouteOption.click();

    // Verify helpful reminder banner appears
    await expect(page.locator("text=Chưa có lộ trình: Vui lòng tìm đường để lọc camera trên tuyến")).toBeVisible();

    // Switch to 'Có ảnh trực tiếp'
    await filterBtn.click();
    const hasImageOption = page.locator("button:has-text('Có ảnh trực tiếp')");
    await expect(hasImageOption).toBeVisible();
    await hasImageOption.click();

    // Switch back to 'Tất cả camera'
    await filterBtn.click();
    const allOption = page.locator("button:has-text('Tất cả camera')");
    await expect(allOption).toBeVisible();
    await allOption.click();
    await expect(mapContainer).toHaveAttribute("data-camera-feature-count", /^[1-9]\d*$/);
  });

  test("2. Real Google OAuth state on /account: Configured credentials, No fake profile, Login button enabled", async ({ page }) => {
    await page.goto("/account");

    // Must show truthful guest state
    await expect(page.locator("text=Bạn chưa đăng nhập")).toBeVisible({ timeout: 10000 });
    await expect(page.locator("text=Khách (Chưa đăng nhập)")).toBeVisible();

    // Must NEVER show fake user "Nguyễn Văn An" or mock demo credentials
    const fakeUser = page.locator("text=Nguyễn Văn An");
    await expect(fakeUser).not.toBeVisible();

    const fakeEmail = page.locator("text=an.nguyen@example.com");
    await expect(fakeEmail).not.toBeVisible();

    // With Google OAuth credentials configured, BLOCKED_CONFIGURATION banner must be hidden
    await expect(page.locator("text=BLOCKED_CONFIGURATION")).not.toBeVisible();

    // Google login button exists and is enabled
    const googleLoginBtn = page.getByRole("button", { name: "Tiếp tục với Google" });
    await expect(googleLoginBtn).toBeVisible();
    await expect(googleLoginBtn).toBeEnabled();

    // Saved places and history must be empty in guest state
    await expect(page.locator("text=Bạn đang ở chế độ khách. Hãy đăng nhập tài khoản để lưu các địa điểm yêu thích.")).toBeVisible();
    await expect(page.locator("text=Bạn đang ở chế độ khách. Các tuyến đường tìm kiếm sẽ không được lưu vào tài khoản.")).toBeVisible();
  });

  test("3. Backend scheduler telemetry endpoint responds with fair rotation metrics", async ({ request }) => {
    const res = await request.get("http://localhost:8000/api/v1/admin/camera-ingestion/status");
    expect(res.status()).toBe(200);
    const data = await res.json();
    expect(data.status).toBe("healthy");
    expect(data.total_registered_cameras).toBe(796);
    expect(data.geolocated_cameras).toBe(796);
    expect(data.tracked_in_scheduler).toBeGreaterThanOrEqual(1);
    expect(data.recent_hour_attempts).toBeGreaterThanOrEqual(1);
  });

  test("4. Google Sign-in button triggers redirect toward accounts.google.com", async ({ page }) => {
    await page.goto("/account");

    const googleLoginBtn = page.getByRole("button", { name: "Tiếp tục với Google" });
    await expect(googleLoginBtn).toBeVisible();
    await expect(googleLoginBtn).toBeEnabled();

    // Intercept navigation request toward Google OAuth authorization endpoint
    const redirectPromise = page.waitForRequest(
      (req) => req.url().startsWith("https://accounts.google.com/o/oauth2/v2/auth"),
      { timeout: 10000 }
    );

    await googleLoginBtn.click();
    const googleReq = await redirectPromise;

    expect(googleReq.url()).toContain("redirect_uri=http%3A%2F%2Flocalhost%3A3000%2Fapi%2Fauth%2Fcallback%2Fgoogle");
    expect(googleReq.url()).toContain("response_type=code");
    expect(googleReq.url()).toContain("scope=openid%20email%20profile");
    expect(googleReq.url()).toContain("code_challenge_method=S256");
  });
});

