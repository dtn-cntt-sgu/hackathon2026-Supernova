import { test, expect } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  page.on("pageerror", (error) => console.error("PAGE ERROR:", error.stack));
  await page.addInitScript(() => {
    localStorage.setItem("safepath_onboarding_completed", "true");
    localStorage.setItem(
      "safepath_tour_state_v1",
      JSON.stringify({
        version: "v1",
        status: "completed",
        dontShowAgain: true,
        tours: { map: true, news: true },
      })
    );
  });
});

const mockRouteData = {
  route_id: "ROUTE_MOCK_1",
  total_distance_km: 4.8,
  estimated_time_mins: 15.5,
  osrm_duration_seconds: 750.0,
  traffic_adjusted_eta_seconds: 930.0,
  traffic_eta_status: "TRAFFIC_ADJUSTED",
  traffic_eta_source: "VERIFIED_CAMERA_AND_NEWS",
  traffic_delay_seconds: 180.0,
  ranking_cost: 1020.0,
  overall_risk: "MODERATE",
  route_status: "ROUTE_CONGESTION_DETECTED",
  is_recommended: true,
  is_fastest: true,
  route_type: "RECOMMENDED_AND_FASTEST",
  ai_explanation: "Tuyến đường có 1 đoạn ùn tắc đã xác thực, dự kiến trễ 3 phút.",
  geojson_path: {
    type: "LineString",
    coordinates: [
      [106.6980, 10.7725],
      [106.7020, 10.7780],
      [106.7080, 10.7890],
      [106.7115, 10.8012],
    ],
  },
  segments: [
    {
      osm_way_id: 101,
      street_name: "Đường Lê Duẩn",
      length_meters: 1200.0,
      risk_level: "UNKNOWN",
      traffic_status: "FREE_FLOW",
      traffic_delay_seconds: 0.0,
      geojson_path: {
        type: "LineString",
        coordinates: [[106.6980, 10.7725], [106.7020, 10.7780]],
      },
      evidence_cameras: [],
    },
    {
      osm_way_id: 102,
      street_name: "Đường Đinh Tiên Hoàng",
      length_meters: 1600.0,
      risk_level: "UNKNOWN",
      traffic_status: "CONGESTED",
      traffic_delay_seconds: 180.0,
      geojson_path: {
        type: "LineString",
        coordinates: [[106.7020, 10.7780], [106.7080, 10.7890]],
      },
      evidence_cameras: [],
    },
    {
      osm_way_id: 103,
      street_name: "Đường Xô Viết Nghệ Tĩnh",
      length_meters: 2000.0,
      risk_level: "UNKNOWN",
      traffic_status: "UNKNOWN",
      traffic_delay_seconds: 0.0,
      geojson_path: {
        type: "LineString",
        coordinates: [[106.7080, 10.7890], [106.7115, 10.8012]],
      },
      evidence_cameras: [],
    },
  ],
  alternative_routes: [
    {
      route_id: "ROUTE_MOCK_2",
      total_distance_km: 5.4,
      estimated_time_mins: 18.0,
      osrm_duration_seconds: 1080.0,
      traffic_delay_seconds: 0.0,
      ranking_cost: 1080.0,
      overall_risk: "UNKNOWN",
      route_status: "ROUTE_FOUND_RISK_UNKNOWN",
      is_recommended: false,
      is_fastest: false,
      route_type: "ALTERNATIVE_1",
      ai_explanation: "Tuyến đường vòng thay thế.",
      geojson_path: {
        type: "LineString",
        coordinates: [
          [106.6980, 10.7725],
          [106.7150, 10.7850],
          [106.7115, 10.8012],
        ],
      },
      segments: [],
    },
  ],
};

test.describe("Traffic Intelligence & Collapsible Sidebar E2E", () => {
  test("Desktop sidebar collapses and expands smoothly via header close button and reopen tab", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/di-duong");
    await expect(page.getByTestId("route-map")).toBeVisible({ timeout: 15000 });

    const collapseBtn = page.getByRole("button", { name: /Thu gọn bảng điều khiển/i });
    await expect(collapseBtn).toBeVisible();

    // Click collapse (inside "KẾ HOẠCH CHUYẾN ĐI" header)
    await collapseBtn.click();
    await page.waitForTimeout(300);

    // Reopen tab appears at top-left edge
    const reopenBtn = page.getByRole("button", { name: /Mở lại bảng điều khiển/i });
    await expect(reopenBtn).toBeVisible();

    // Click reopen
    await reopenBtn.click();
    await page.waitForTimeout(300);

    await expect(page.getByRole("button", { name: /Thu gọn bảng điều khiển/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /Vui lòng chọn Điểm đi và Điểm đến/i })).toBeVisible();
  });

  test("Manual traffic toggle is removed; map controls are clean and responsive", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/di-duong");
    await expect(page.getByTestId("route-map")).toBeVisible({ timeout: 15000 });

    // P3 Requirement: The manual "Giao thông" toggle button must NOT be present
    const trafficToggle = page.getByRole("button", { name: /Giao thông/i });
    await expect(trafficToggle).not.toBeVisible();

    // Map controls and route planner remain clean and functional
    await expect(page.getByRole("button", { name: "Chợ Bến Thành" })).toBeVisible();
    await expect(page.getByRole("button", { name: /Vui lòng chọn Điểm đi và Điểm đến/i })).toBeVisible();
  });

  test("Route search populates authoritative Đề xuất tab, ETA transparency and traffic badges", async ({ page }) => {
    // Intercept safe route search API
    await page.route("**/api/v1/routes/search*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockRouteData),
      });
    });

    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/di-duong");
    await expect(page.getByTestId("route-map")).toBeVisible({ timeout: 15000 });

    // Pick presets
    await page.getByRole("button", { name: "Chợ Bến Thành" }).click();
    await page.getByRole("button", { name: "Ngã tư Hàng Xanh" }).click();

    const searchBtn = page.getByRole("button", { name: "Tìm tuyến đường", exact: true });
    await searchBtn.click();

    // Wait for route results
    await expect(page.locator("[data-selected-route-id]")).toBeVisible({ timeout: 15000 });

    // 1. Verify Authoritative 'Đề xuất' tab exists and is selected
    const deXuatTab = page.getByRole("tab", { name: /Đề xuất/i });
    await expect(deXuatTab).toBeVisible();
    await expect(deXuatTab).toHaveAttribute("aria-selected", "true");

    // 2. Verify Realistic ETA transparency badge
    await expect(page.getByText(/\+3p trễ/i)).toBeVisible();
    await expect(page.getByText(/ETA đã cộng 3 phút do mật độ\/ùn tắc/i)).toBeVisible();

    // 3. Verify Traffic Legend on map
    const legend = page.getByTestId("traffic-legend");
    await expect(legend).toBeVisible();
    await expect(legend.getByText(/Tình trạng giao thông/i)).toBeVisible();
    await expect(legend.getByText(/Thông thoáng/i)).toBeVisible();
    await expect(legend.getByText(/Ùn tắc/i)).toBeVisible();

    // 4. Verify step details expandable list with segment traffic badges
    const detailsToggle = page.getByRole("button", { name: /Xem từng chặng/i });
    await expect(detailsToggle).toBeVisible();
    await detailsToggle.click();

    await expect(page.getByText("Đường Lê Duẩn").first()).toBeVisible();
    await expect(page.getByText("Đường Đinh Tiên Hoàng").first()).toBeVisible();
    await expect(page.getByText("Thông thoáng").first()).toBeVisible();
    await expect(page.getByText("Ùn tắc").first()).toBeVisible();
  });
});
