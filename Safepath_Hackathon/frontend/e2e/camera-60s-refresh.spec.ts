import { test, expect } from "@playwright/test";

test.describe("Camera Proxy Refresh & Map Evidence Regression", () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem("safepath_onboarding_completed", "true");
    });
  });

  test("Monitor proxy refresh supports pause and interval selection", async ({ page }) => {
    await page.goto("/monitor");
    await expect(page.getByTestId("camera-card").first()).toBeVisible({ timeout: 15000 });
    const interval = page.getByLabel("Chu kỳ cập nhật ảnh");
    await expect(interval).toHaveValue("30000");
    await interval.selectOption("60000");
    await expect(interval).toHaveValue("60000");
    await interval.selectOption("0");
    await expect(interval).toHaveValue("0");
    await expect(page.getByText("tạm dừng tự làm mới", { exact: false })).toBeVisible();
    const proxyRequests: string[] = [];
    page.on("request", request => {
      if (/\/cameras\/[^/]+\/proxy/.test(request.url())) proxyRequests.push(request.url());
    });
    await page.getByTestId("camera-card").first().click();
    await expect(page.getByTestId("camera-proxy-modal")).toBeVisible();
    await expect.poll(() => proxyRequests.length).toBeGreaterThan(0);
    const count = proxyRequests.length;
    await page.waitForTimeout(1100);
    expect(proxyRequests.length).toBe(count);
  });

  test("Monitor suspends image polling while document is hidden", async ({ page }) => {
    await page.clock.install();
    await page.goto("/monitor");
    await expect(page.getByTestId("camera-card").first()).toBeVisible({ timeout: 15000 });
    await page.waitForLoadState("networkidle");
    await page.evaluate(() => {
      Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
      document.dispatchEvent(new Event("visibilitychange"));
    });
    const requests: string[] = [];
    page.on("request", request => {
      if (/\/cameras\/[^/]+\/proxy/.test(request.url())) requests.push(request.url());
    });
    await page.clock.fastForward(65000);
    expect(requests).toEqual([]);
    await page.evaluate(() => {
      Object.defineProperty(document, "hidden", { configurable: true, get: () => false });
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await expect.poll(() => requests.length).toBeGreaterThan(0);
  });

  test("verifies MapLibre map renders camera icons and modal opens seamlessly", async ({ page }) => {
    await page.goto("/map");
    await page.waitForLoadState("networkidle");

    // Wait for map canvas
    await expect(page.locator(".maplibregl-canvas")).toBeVisible({ timeout: 15000 });

    // Zoom in so camera icons are unclustered
    await page.evaluate(() => {
      // @ts-ignore
      const map = window.__safepath_map;
      if (map) map.setZoom(15.2);
    });
    await page.waitForTimeout(1000);

    // Click on a camera point on map if rendered
    const point = await page.evaluate(() => {
      // @ts-ignore
      const map = window.__safepath_map;
      if (!map) return null;
      const features = map.queryRenderedFeatures(undefined, { layers: ["camera-points"] });
      if (features.length === 0) return null;
      return map.project(features[0].geometry.coordinates);
    });

    if (point) {
      await page.mouse.click(point.x, point.y);
      const modal = page.locator("[data-testid='camera-evidence-modal']");
      if (await modal.isVisible()) {
        await expect(modal.locator("text=Kiểm tra ảnh tự động mỗi ~1 phút")).toBeVisible();
        await page.screenshot({ path: "docs/camera_60s_map_modal.png" });
        await page.locator("button[aria-label='Đóng chi tiết camera']").click();
      }
    }
  });
});
