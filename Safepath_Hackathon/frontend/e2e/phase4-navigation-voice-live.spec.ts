import { test, expect, type WebSocketRoute } from "@playwright/test";

const installSpeechSpy = async (page: import("@playwright/test").Page) => {
  await page.addInitScript(() => {
    const probe = { spoken: [] as string[], cancelled: 0, watches: 0, clearedWatches: 0 };
    (window as any).__speechProbe = probe;
    const synthesis = window.speechSynthesis;
    Object.defineProperty(synthesis, "speak", { configurable: true, value: (utterance: SpeechSynthesisUtterance) => { probe.spoken.push(utterance.text); } });
    Object.defineProperty(synthesis, "cancel", { configurable: true, value: () => { probe.cancelled++; } });
    Object.defineProperty(synthesis, "speaking", { configurable: true, get: () => false });
    Object.defineProperty(synthesis, "getVoices", { configurable: true, value: () => [] });
    Object.defineProperty(navigator.geolocation, "watchPosition", { configurable: true, value: (success: PositionCallback) => { (window as any).__locationWatchCallback = success; probe.watches++; return probe.watches; } });
    Object.defineProperty(navigator.geolocation, "clearWatch", { configurable: true, value: () => { probe.clearedWatches++; } });
  });
};
const probe = (page: import("@playwright/test").Page) => page.evaluate(() => (window as any).__speechProbe as { spoken: string[]; cancelled: number; watches: number; clearedWatches: number });
const alertMessage = (eventId: string) => JSON.stringify({
  event_id: eventId, type: "CRITICAL_FLOOD_ALERT", severity: "CRITICAL", source: "camera_vision:ONNX",
  cam_id: "unverified-camera", risk_level: "CRITICAL", message: "Cảnh báo thử nghiệm không liên quan tuyến",
  observed_at: new Date().toISOString(), expiry: new Date(Date.now() + 60000).toISOString(),
});

test("speech starts only after explicit opt-in and Start; pause, stop and alert bursts stay silent", async ({ page }) => {
  await installSpeechSpy(page);
  let socket: WebSocketRoute | null = null;
  await page.routeWebSocket("**/ws/alerts", (ws) => { socket = ws; });
  await page.goto("/map");
  await expect(page.locator(".maplibregl-canvas")).toBeVisible({ timeout: 15000 });
  await expect(page.locator("[data-navigation-state='idle']")).toBeVisible();
  await expect.poll(async () => Boolean(socket)).toBe(true);
  socket!.send(alertMessage("before-navigation"));
  await page.getByRole("button", { name: "Chợ Bến Thành" }).click();
  await page.getByRole("button", { name: "Ngã tư Hàng Xanh" }).click();
  await page.getByRole("button", { name: "Tìm tuyến đường", exact: true }).click();
  await expect(page.locator("[data-navigation-state='route_preview']")).toBeVisible({ timeout: 20000 });
  await expect(page.getByRole("button", { name: "Bắt đầu chỉ đường" })).toBeEnabled();
  expect((await probe(page)).spoken).toHaveLength(0);
  socket!.send(alertMessage("still-preview"));
  await page.getByRole("checkbox", { name: "Bật giọng hướng dẫn khi bắt đầu" }).check();
  expect((await probe(page)).spoken).toHaveLength(0);
  await page.getByRole("button", { name: "Bắt đầu chỉ đường" }).click();
  await expect(page.locator("[data-navigation-state='navigating']")).toBeVisible();
  await expect.poll(async () => (await probe(page)).spoken.length).toBe(1);
  expect((await probe(page)).spoken[0]).toMatch(/Bắt đầu.*\d+ m/);
  for (let i = 0; i < 8; i++) socket!.send(alertMessage(`burst-${i}`));
  await expect.poll(async () => (await probe(page)).spoken.length).toBe(1);
  const cancelsBeforePause = (await probe(page)).cancelled;
  await page.getByRole("button", { name: "Tạm dừng" }).click();
  await expect(page.locator("[data-navigation-state='paused']")).toBeVisible();
  expect((await probe(page)).cancelled).toBeGreaterThan(cancelsBeforePause);
  socket!.send(alertMessage("while-paused"));
  await page.getByRole("button", { name: "Tiếp tục" }).click();
  await expect(page.locator("[data-navigation-state='navigating']")).toBeVisible();
  expect((await probe(page)).spoken).toHaveLength(1);
  const cancelsBeforeVisibility = (await probe(page)).cancelled;
  await page.evaluate(() => { Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" }); document.dispatchEvent(new Event("visibilitychange")); });
  await expect(page.locator("[data-navigation-state='paused']")).toBeVisible();
  expect((await probe(page)).cancelled).toBeGreaterThan(cancelsBeforeVisibility);
  await page.evaluate(() => { Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" }); document.dispatchEvent(new Event("visibilitychange")); });
  await expect(page.locator("[data-navigation-state='paused']")).toBeVisible();
  await page.getByRole("button", { name: "Tiếp tục" }).click();
  expect((await probe(page)).spoken).toHaveLength(1);
  const cancelsBeforeStop = (await probe(page)).cancelled;
  await page.getByRole("button", { name: "Dừng chỉ đường" }).click();
  await expect(page.locator("[data-navigation-state='ended']")).toBeVisible();
  expect((await probe(page)).cancelled).toBeGreaterThan(cancelsBeforeStop);
  socket!.send(alertMessage("after-stop"));
  expect((await probe(page)).spoken).toHaveLength(1);
});

test("voice is muted by default; tracking starts only with consent and stops on pause", async ({ page }) => {
  await installSpeechSpy(page);
  await page.goto("/map");
  await expect(page.locator(".maplibregl-canvas")).toBeVisible({ timeout: 15000 });
  await page.getByRole("button", { name: "Chợ Bến Thành" }).click();
  await page.getByRole("button", { name: "Ngã tư Hàng Xanh" }).click();
  await page.getByRole("button", { name: "Tìm tuyến đường", exact: true }).click();
  await expect(page.locator("[data-navigation-state='route_preview']")).toBeVisible({ timeout: 20000 });
  expect((await probe(page)).watches).toBe(0);
  await page.getByRole("checkbox", { name: "Theo dõi vị trí của tôi khi đi" }).check();
  expect((await probe(page)).watches).toBe(0);
  await page.getByRole("button", { name: "Bắt đầu chỉ đường" }).click();
  await expect.poll(async () => (await probe(page)).watches).toBe(1);
  expect((await probe(page)).spoken).toHaveLength(0);
  await page.getByRole("button", { name: "Đọc lại" }).count().then((count) => expect(count).toBe(1));
  await expect(page.getByRole("button", { name: "Đọc lại" })).toBeDisabled();
  await page.getByRole("button", { name: "Tạm dừng" }).click();
  await expect.poll(async () => (await probe(page)).clearedWatches).toBe(1);
  expect((await probe(page)).spoken).toHaveLength(0);
});

test("switching the selected live route cancels speech and returns to preview", async ({ page }) => {
  await installSpeechSpy(page);
  await page.goto("/map");
  await expect(page.locator(".maplibregl-canvas")).toBeVisible({ timeout: 15000 });
  await page.getByRole("button", { name: "Chợ Bến Thành" }).click();
  await page.getByRole("button", { name: "Ngã tư Hàng Xanh" }).click();
  await page.getByRole("button", { name: "Tìm tuyến đường", exact: true }).click();
  await expect(page.locator("[data-navigation-state='route_preview']")).toBeVisible({ timeout: 20000 });
  const alternative = page.getByRole("button", { name: /^Chọn Đường khác/ }).first();
  if (!await alternative.count()) return;
  await page.getByRole("checkbox", { name: "Bật giọng hướng dẫn khi bắt đầu" }).check();
  await page.getByRole("button", { name: "Bắt đầu chỉ đường" }).click();
  await expect.poll(async () => (await probe(page)).spoken.length).toBe(1);
  const before = (await probe(page)).cancelled;
  await alternative.click();
  await expect(page.locator("[data-navigation-state='route_preview']")).toBeVisible();
  expect((await probe(page)).cancelled).toBeGreaterThan(before);
  expect((await probe(page)).spoken).toHaveLength(1);
});


test("consented position updates announce the next real OSRM turn once", async ({ page }) => {
  await installSpeechSpy(page);
  await page.goto("/map");
  await expect(page.locator(".maplibregl-canvas")).toBeVisible({ timeout: 15000 });
  const responsePromise = page.waitForResponse((response) => response.url().includes("/api/v1/routes/search") && response.request().method() === "POST");
  await page.getByRole("button", { name: "Chợ Bến Thành" }).click();
  await page.getByRole("button", { name: "Ngã tư Hàng Xanh" }).click();
  await page.getByRole("button", { name: "Tìm tuyến đường", exact: true }).click();
  const response = await responsePromise;
  expect(response.status()).toBe(200);
  const data = await response.json();
  const routes = [data, ...(data.alternative_routes || [])];
  const selected = routes.reduce((best: any, route: any) => route.estimated_time_mins < best.estimated_time_mins ? route : best);
  const next = selected.segments[1];
  expect(next.maneuver_type).toBe("turn");
  expect(next.maneuver_location).toHaveLength(2);
  await expect(page.locator("[data-navigation-state='route_preview']")).toBeVisible();
  await page.getByRole("checkbox", { name: "Bật giọng hướng dẫn khi bắt đầu" }).check();
  await page.getByRole("checkbox", { name: "Theo dõi vị trí của tôi khi đi" }).check();
  await page.getByRole("button", { name: "Bắt đầu chỉ đường" }).click();
  await expect.poll(async () => (await probe(page)).watches).toBe(1);
  expect((await probe(page)).spoken).toHaveLength(1);
  const [lng, lat] = next.maneuver_location;
  await page.evaluate(({ lng, lat }) => {
    const callback = (window as any).__locationWatchCallback as PositionCallback;
    for (let i = 0; i < 5; i++) callback({ coords: { longitude: lng, latitude: lat, accuracy: 10 } } as GeolocationPosition);
  }, { lng, lat });
  await expect.poll(async () => (await probe(page)).spoken.length).toBe(2);
  const spoken = (await probe(page)).spoken[1];
  expect(spoken).toMatch(/Rẽ (trái|phải)/);
  expect(spoken).toContain(`${Math.round(next.length_meters)} m`);
  await expect(page.locator("[data-navigation-state='navigating']")).toContainText(spoken);
});
