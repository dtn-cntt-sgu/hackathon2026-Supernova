import { test, expect } from "@playwright/test";

// Live only: no page.route interception or fabricated GeoJSON.
test("OSRM route appears on the live map", async ({ page }) => {
  const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  const response = await page.request.post(`${apiBase}/api/v1/routes/search`, {
    data: {
      origin: { lat: 10.7725, lng: 106.6980 },
      destination: { lat: 10.8012, lng: 106.7115 },
    },
  });
  expect(response.status()).toBe(200);
  const route = await response.json();
  expect(route.geojson_path.type).toBe("LineString");
  expect(route.geojson_path.coordinates.length).toBeGreaterThanOrEqual(10);
  expect(route.total_distance_km).toBeGreaterThan(0);
  expect(route.estimated_time_mins).toBeGreaterThan(0);

  page.on("console", (msg) => console.log(`[BROWSER CONSOLE] ${msg.type()}: ${msg.text()}`));
  page.on("pageerror", (err) => console.error(`[BROWSER ERROR]`, err));

  await page.goto("/map");
  await page.getByRole("button", { name: "Chợ Bến Thành" }).click();
  await page.getByRole("button", { name: "Ngã tư Hàng Xanh" }).click();
  await page.getByRole("button", { name: "Tìm tuyến đường" }).click();
  await expect(page.getByText("Tuyến đang chọn")).toBeVisible({ timeout: 15000 });
  await expect(page.locator(".maplibregl-canvas")).toBeVisible();
  await expect(page.locator("[data-route-vertices]")).toHaveAttribute("data-route-vertices", /^\d{2,}$/);
  await expect(page.locator("[data-tiles-ready='true']")).toBeVisible({ timeout: 15000 });
  await expect(page.getByText("Không tải được bản đồ.")).toHaveCount(0);
  await expect(page.locator(".maplibregl-marker").filter({ hasText: /^A$/ })).toBeVisible();
  await expect(page.locator(".maplibregl-marker").filter({ hasText: /^B$/ })).toBeVisible();
  await expect(page.getByRole("link", { name: /CARTO|OpenFreeMap/i })).toBeVisible();
  await expect(page.getByRole("link", { name: "OpenStreetMap" })).toBeVisible();
  await page.screenshot({ path: "test-results/osrm-live-map-primary.png", fullPage: true });
  await page.getByRole("button", { name: "Zoom in" }).click();
  await page.getByRole("button", { name: "Zoom in" }).click();
  await page.waitForTimeout(600);
  await page.screenshot({ path: "test-results/osrm-live-map-detail.png", fullPage: true });
  const candidateButton = page.getByRole("button", { name: /^Chọn Đường khác/ }).first();
  if (await candidateButton.count()) {
    await candidateButton.click();
    await expect(page.getByText("Tuyến đang chọn")).toBeVisible();
    await expect(page.locator("[data-route-vertices]")).toHaveAttribute("data-route-vertices", /^\d{2,}$/);
    await page.screenshot({ path: "test-results/osrm-live-map-alternative.png", fullPage: true });
  }
});

test("five independent HCMC pairs render real routes on tiles", async ({ page }) => {
  test.setTimeout(90000);
  await page.goto("/map");
  const pairs = [
    ["Chợ Bến Thành", "Ngã tư Hàng Xanh"],
    ["Sân bay Tân Sơn Nhất", "Chợ Bến Thành"],
    ["Landmark 81", "Ngã tư Hàng Xanh"],
    ["Nhà thờ Đức Bà", "Landmark 81"],
    ["Nguyễn Hữu Cảnh", "Sân bay Tân Sơn Nhất"],
  ];
  for (let index = 0; index < pairs.length; index++) {
    const [originQuery, destQuery] = pairs[index];

    // Fill origin via scoped testId
    const originBox = page.getByTestId("origin-combobox");
    const originInput = originBox.getByRole("combobox");
    await originInput.fill(originQuery);
    const originOption = originBox.getByRole("option").filter({ hasText: originQuery }).first();
    await expect(originOption).toBeVisible({ timeout: 5000 });
    await originOption.click();
    await expect(originBox.getByRole("listbox")).toHaveCount(0);

    // Fill destination via scoped testId
    const destBox = page.getByTestId("destination-combobox");
    const destInput = destBox.getByRole("combobox");
    await destInput.fill(destQuery);
    const destOption = destBox.getByRole("option").filter({ hasText: destQuery }).first();
    await expect(destOption).toBeVisible({ timeout: 5000 });
    await destOption.click();
    await expect(destBox.getByRole("listbox")).toHaveCount(0);

    const searchBtn = page.getByRole("button", { name: "Tìm tuyến đường" });
    await expect(searchBtn).toBeEnabled({ timeout: 5000 });
    await searchBtn.click();

    await expect(page.getByText("Tuyến đang chọn")).toBeVisible({ timeout: 15000 });
    await expect(page.locator("[data-route-vertices]")).toHaveAttribute("data-route-vertices", /^\d{2,}$/);
    await expect(page.locator("[data-tiles-ready='true']")).toBeVisible({ timeout: 15000 });
    await expect(page.getByText("Không tải được bản đồ.")).toHaveCount(0);
    await page.screenshot({ path: `test-results/osrm-hcm-pair-${index + 1}.png`, fullPage: true });
  }
});
