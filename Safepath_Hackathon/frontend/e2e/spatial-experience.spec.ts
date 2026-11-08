import { test, expect } from "@playwright/test";
import type { CameraEvidence, CameraSummary, SafeRouteResponse, WeatherTideSignal } from "../src/types/contracts";

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("safepath_tour_state_v1", JSON.stringify({ version: "v1", status: "skipped", updatedAt: new Date().toISOString() })));
});

// Acceptance tests use the running backend, OSRM, tiles and camera endpoints. No interception.
test("overview numbers and four chapters reflect real backend responses", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  const errors: string[] = []; page.on("pageerror", error => errors.push(error.message));
  const summaryResponse = page.waitForResponse(r => r.url().endsWith("/api/v1/cameras/summary"));
  const weatherResponse = page.waitForResponse(r => r.url().endsWith("/api/v1/weather-tide"));
  await page.goto("/");
  const summary: CameraSummary = await (await summaryResponse).json();
  const weather: WeatherTideSignal = await (await weatherResponse).json();
  await expect(page.getByTestId("network-count")).toHaveText(String(summary.total_registered));
  await expect(page.getByTestId("recent-image-count")).toHaveText(String(summary.valid_images_count));
  await page.screenshot({ path: "test-results/real-overview-desktop.png" });
  for (const [index, title] of ["Mạng lưới camera", "Ảnh và phân tích", "Bản tin giao thông", "Tìm tuyến đường"].entries()) {
    await page.locator(".chapter-nav").getByRole("button", { name: title, exact: true }).click();
    await expect(page.locator(".story-viewport")).toHaveAttribute("data-scene", String(index));
    await expect(page.locator(".story-scene.is-active")).toHaveCount(1);
    if (index === 2) {
      if (weather.rain_mm_per_hour === null) await expect(page.locator(".observation-context")).toContainText(/Chưa có dữ liệu|Dữ liệu cũ/);
      await page.screenshot({ path: "test-results/real-environment.png" });
    }
  }
  await expect(page.locator("body")).not.toContainText(/48\.2%|800\+|RISK SCORE · DEMO|Giả lập mưa|45 phút/);
  await page.locator(".route-ready a[href='/map']").click();
  await expect(page).toHaveURL(/\/map$/);
  expect(errors).toEqual([]);
});

test("camera evidence uses the selected real camera, preserving absent flood measurements", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  const camerasResponse = page.waitForResponse(r => r.url().endsWith("/api/v1/cameras"));
  await page.goto("/");
  const cameras: CameraEvidence[] = await (await camerasResponse).json();
  expect(cameras.length).toBeGreaterThan(0);
  const camera = cameras.find(c => c.has_image && c.model_status === "INFERENCE_COMPLETED") || cameras.find(c => c.has_image) || cameras[0];
  await page.getByRole("button", { name: "Ảnh và phân tích", exact: true }).click();
  await page.getByRole("combobox", { name: "Chọn camera quan trắc" }).selectOption(camera.cam_id);
  await expect(page.locator(".scene-note").filter({ hasText: camera.name })).toBeVisible();
  if (!camera.captured_at) await expect(page.getByTestId("observation-status")).not.toHaveText("LIVE");
  if (camera.flood_ratio === null) await expect(page.locator(".actual-water-status")).toContainText("Chưa xác minh");
  if (camera.has_image && camera.model_status === "INFERENCE_COMPLETED") {
    await expect(page.getByTestId("observed-vehicle-count")).toContainText(String(camera.vehicle_count ?? "—"));
    await expect(page.getByRole("img", { name: `Ảnh gốc ${camera.name}`, exact: true })).toHaveAttribute("src", new RegExp(camera.cam_id));
  }
  await page.screenshot({ path: "test-results/real-camera-evidence.png" });
});

test("spatial map renders the exact geometry returned by live OSRM search", async ({ page }) => {
  test.setTimeout(45000);
  await page.goto("/map");
  await expect(page.getByRole("button", { name: /Giả lập|mô phỏng/i })).toHaveCount(0);
  await page.getByRole("button", { name: "Chợ Bến Thành", exact: true }).click();
  await page.getByRole("button", { name: "Ngã tư Hàng Xanh", exact: true }).click();
  const response = page.waitForResponse(r => r.url().includes("/api/v1/routes/search") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Tìm tuyến đường", exact: true }).click();
  const network = await response;
  expect(network.status()).toBe(200);
  const route: SafeRouteResponse = await network.json();
  expect(route.geojson_path.coordinates.length).toBeGreaterThan(10);
  await expect(page.locator("[data-selected-route-id]")).toHaveAttribute("data-selected-route-id", route.route_id, { timeout: 20000 });
  const rendered = await page.evaluate(() => {
    const map = (window as any).__safepath_map;
    return map.getSource("route-recommended-source")._data.features[0].geometry;
  });
  expect(rendered).toEqual(route.geojson_path);
  if (route.overall_risk === "UNKNOWN") await expect(page.getByTestId("route-explanation")).toContainText("Chưa đủ dữ liệu");
  const dimension = page.locator(".spatial-dock button");
  const wasPressed = await dimension.getAttribute("aria-pressed");
  await dimension.click();
  await expect(dimension).toHaveAttribute("aria-pressed", wasPressed === "true" ? "false" : "true");
  await page.screenshot({ path: "test-results/real-osrm-spatial-map.png" });
});

test("mobile overview and map fit the viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByTestId("network-count")).toHaveText(/^\d+$/);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: "test-results/real-overview-mobile.png" });
  await page.locator(".hero-copy a[href='/map']").click();
  await expect(page.locator(".floating-navigator")).toBeVisible();
  await expect(page.getByRole("button", { name: "Thông tin quan trắc và giải thích tuyến" })).toHaveCount(0);
  await expect(page.getByTestId("environment-widget")).toContainText("Thời tiết & Thủy văn");
  await page.screenshot({ path: "test-results/real-map-mobile.png" });
});

test("real websocket ignores the removed simulation command and still answers heartbeat", async ({ page }) => {
  await page.goto("/map");
  const messages = await page.evaluate(() => new Promise<string[]>((resolve, reject) => {
    const socket = new WebSocket("ws://localhost:8000/ws/alerts");
    const received: string[] = [];
    const timer = setTimeout(() => { socket.close(); reject(new Error("WebSocket timeout")); }, 5000);
    socket.onmessage = event => {
      received.push(event.data);
      if (event.data === "pong") { clearTimeout(timer); socket.close(); resolve(received); }
      else if (JSON.parse(event.data).type === "CONNECTION_ESTABLISHED") {
        socket.send("demo:extreme-rain"); socket.send("ping");
      }
    };
    socket.onerror = () => { clearTimeout(timer); reject(new Error("WebSocket unavailable")); };
  }));
  expect(messages).toHaveLength(2);
  expect(messages.join(" ")).not.toContain("DEMO_FLOOD_ALERT");
});
