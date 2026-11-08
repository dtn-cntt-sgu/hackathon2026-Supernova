import { test, expect } from "@playwright/test";

const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

test.beforeEach(({ page }) => page.on("pageerror", (error) => console.error("PAGE ERROR:", error.stack)));

test("live OSRM alternatives select their own geometry, camera toggle preserves route", async ({ page }) => {
  test.setTimeout(60000);
  const response = await page.request.post(`${apiBase}/api/v1/routes/search`, { data: {
    origin: { lat: 10.7725, lng: 106.6980 }, destination: { lat: 10.8012, lng: 106.7115 },
  } });
  expect(response.status()).toBe(200);
  const data = await response.json();
  const routes = [data, ...(data.alternative_routes || [])];
  await page.goto("/map");
  await expect(page.locator(".maplibregl-canvas")).toBeVisible({ timeout: 15000 });
  await page.getByRole("button", { name: "Chợ Bến Thành" }).click();
  await page.getByRole("button", { name: "Ngã tư Hàng Xanh" }).click();
  await page.getByRole("button", { name: "Tìm tuyến đường", exact: true }).click();
  await expect(page.locator("[data-selected-route-id]")).toBeVisible({ timeout: 20000 });
  await expect(page.getByRole("link", { name: "OpenStreetMap" }).first()).toBeVisible();
  await expect(page.getByRole("link", { name: /CARTO|OpenFreeMap/i })).toBeVisible();
  const selected = page.locator("[data-selected-route-id]");
  const firstId = await selected.getAttribute("data-selected-route-id");
  const firstGeometry = await selected.getAttribute("data-route-geometry-key");
  const firstExplanation = await page.getByTestId("route-explanation").textContent();
  if (await page.locator("[data-testid='camera-evidence-modal']").isVisible()) {
    await page.keyboard.press("Escape");
  }
  await expect(page.getByRole("switch", { name: "Hiển thị camera" })).toHaveAttribute("aria-checked", "false");
  await expect(selected).toHaveAttribute("data-route-above-camera", "true");
  await page.getByRole("switch", { name: "Hiển thị camera" }).click();
  await expect(page.getByRole("switch", { name: "Hiển thị camera" })).toHaveAttribute("aria-checked", "true");
  await expect(selected).toHaveAttribute("data-camera-feature-count", /^[1-9]\d*$/);
  await page.getByRole("switch", { name: "Hiển thị camera" }).click();
  await expect(page.locator("[data-camera-feature-count]")).toHaveAttribute("data-camera-feature-count", "0");
  await expect(selected).toHaveAttribute("data-route-vertices", /^\d{2,}$/);
  await expect(selected).toHaveAttribute("data-map-zoom", /^\d+\.\d{3}$/);
  const previousZoom = await selected.getAttribute("data-map-zoom");
  await page.getByRole("button", { name: "Zoom in" }).click();
  await expect(selected).not.toHaveAttribute("data-map-zoom", previousZoom!);
  const manualZoom = await selected.getAttribute("data-map-zoom");
  await page.getByRole("switch", { name: "Hiển thị camera" }).click();
  await expect(selected).toHaveAttribute("data-map-zoom", manualZoom!);
  await page.getByRole("switch", { name: "Hiển thị camera" }).click();
  await page.getByRole("button", { name: /^Chỉ đường$/ }).click();
  await page.getByRole("button", { name: /^1\./ }).first().click();
  await expect(selected).toHaveAttribute("data-highlight-vertices", /^\d+$/);
  if (routes.length > 1) {
    await page.getByRole("button", { name: /^Chọn Đường khác/ }).first().click();
    await expect(selected).not.toHaveAttribute("data-selected-route-id", firstId!);
    await expect(selected).not.toHaveAttribute("data-route-geometry-key", firstGeometry!);
    await expect(page.getByTestId("route-explanation")).not.toHaveText(firstExplanation!);
    await expect(selected).not.toHaveAttribute("data-highlight-vertices", /^\d+$/);
    await expect(page.getByRole("button", { name: /^Chỉ đường$/ })).toBeVisible();
  } else {
    await expect(page.getByText("Chỉ tìm được một tuyến hợp lệ.")).toBeVisible();
  }
});

test("one live route reports no alternative", async ({ page }) => {
  const response = await page.request.post(`${apiBase}/api/v1/routes/search`, { data: {
    origin: { lat: 10.8185, lng: 106.6588 }, destination: { lat: 10.7725, lng: 106.6980 },
  } });
  expect(response.status()).toBe(200);
  const data = await response.json();
  expect(data.alternative_routes || []).toHaveLength(0);
  await page.goto("/map");
  await expect(page.locator(".maplibregl-canvas")).toBeVisible({ timeout: 15000 });
  await page.getByRole("button", { name: "Chợ Bến Thành" }).click();
  await page.getByRole("button", { name: "Sân bay Tân Sơn Nhất" }).click();
  await expect(page.getByTestId("destination-combobox").getByRole("combobox")).toHaveValue("Sân bay Tân Sơn Nhất");
  await page.getByRole("button", { name: "Đảo chiều lộ trình" }).click();
  await expect(page.getByTestId("origin-combobox").getByRole("combobox")).toHaveValue("Sân bay Tân Sơn Nhất");
  await page.getByRole("button", { name: "Tìm tuyến đường", exact: true }).click();
  await expect(page.getByText("Chỉ tìm được một tuyến hợp lệ.")).toBeVisible({ timeout: 20000 });
  await expect(page.locator("[data-route-vertices]")).toBeVisible();
});

test("mobile sheet leaves map visible without horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/map");
  await expect(page.locator(".maplibregl-canvas")).toBeVisible({ timeout: 15000 });
  await expect(page.getByRole("button", { name: "Mở bảng tuyến đường" })).toBeVisible();
  await page.getByRole("button", { name: "Mở bảng tuyến đường" }).click();
  await page.getByRole("button", { name: "Chợ Bến Thành" }).click();
  await page.getByRole("button", { name: "Ngã tư Hàng Xanh" }).click();
  await page.getByRole("button", { name: "Tìm tuyến đường", exact: true }).click();
  await expect(page.locator("[data-route-vertices]")).toBeVisible({ timeout: 20000 });
  const metrics = await page.evaluate(() => ({ documentWidth: document.documentElement.scrollWidth, viewport: innerWidth }));
  expect(metrics.documentWidth).toBeLessThanOrEqual(metrics.viewport);
  await expect(page.getByRole("switch", { name: "Hiển thị camera" })).toBeVisible();
  const attribution = page.getByRole("link", { name: "OpenStreetMap" }).first();
  await expect(attribution).toBeVisible();
  const attributionBox = await attribution.boundingBox();
  const sheetBox = await page.locator("aside").boundingBox();
  expect(attributionBox).toBeTruthy();
  expect(sheetBox).toBeTruthy();
  await page.screenshot({ path: "test-results/phase3-mobile-route.png", fullPage: true });
});

test("404 and 503 show retry without fabricated geometry", async ({ page }) => {
  for (const [status, code] of [[404, "NO_ROUTE_FOUND"], [503, "ROUTING_PROVIDER_UNAVAILABLE"]] as const) {
    await page.route("**/api/v1/routes/search", async (route) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify({ detail: { code, message: "Tuyến không khả dụng" } }) }));
    await page.goto("/map");
    await expect(page.locator(".maplibregl-canvas")).toBeVisible({ timeout: 15000 });
    await page.getByRole("button", { name: "Chợ Bến Thành" }).click();
    await page.getByRole("button", { name: "Ngã tư Hàng Xanh" }).click();
    await page.getByRole("button", { name: "Tìm tuyến đường", exact: true }).click();
    await expect(page.getByRole("button", { name: "Thử lại" })).toBeVisible();
    await expect(page.locator("[data-route-vertices]")).toHaveCount(0);
    await page.unrouteAll();
  }
});
