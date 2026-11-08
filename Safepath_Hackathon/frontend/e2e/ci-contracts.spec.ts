import { test, expect } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("safepath_tour_state_v1", JSON.stringify({version:"v1",status:"skipped",updatedAt:new Date().toISOString()})));
  // Browser contract fixtures only: CI has no licensed camera feed or OAuth identity.
  await page.route("**/api/v1/**", route => {
    const path = new URL(route.request().url()).pathname;
    const body = path.endsWith("/cameras") ? [] : path.includes("user/") ? {detail:{code:"UNAUTHORIZED"}} : {};
    return route.fulfill({status:path.includes("user/") ? 401 : 200, json:body});
  });
});

test("guest report form requires authentication and has no fabricated history", async ({ page }) => {
  await page.goto("/dashboard");
  await expect(page.getByRole("heading", {name:"Báo cáo cộng đồng"})).toBeVisible();
  await expect(page.getByRole("button", {name:"Đăng nhập Google để gửi báo cáo"})).toBeVisible();
  await expect(page.getByRole("button", {name:"Gửi báo cáo", exact:true})).toHaveCount(0);
});

test("guest account remains truthful when OAuth configuration is missing", async ({ page }) => {
  await page.route("**/api/auth/config", route => route.fulfill({json:{google_oauth_configured:false,status:"BLOCKED_CONFIGURATION"}}));
  await page.goto("/account");
  await expect(page.getByText("Bạn chưa đăng nhập", {exact:true})).toBeVisible();
  await expect(page.getByText("an.nguyen@example.com", {exact:true})).toHaveCount(0);
});

test("NO_SAFE_ROUTE has a warning and no safety recommendation badge", async ({ page }) => {
  const geometry = {type:"LineString",coordinates:[[106.698,10.7725],[106.699,10.773],[106.7,10.774]]};
  const segment = {segment_id:"ci-edge",street_name:"CI blocked edge",length_meters:250,risk_score:95,risk_level:"CRITICAL",evidence_cameras:[],traffic_status:"CLOSED",is_closed:true,geojson_path:geometry,explanation:"CI contract fixture: confirmed obstruction"};
  const result = {route_id:"ci-nosafe",total_distance_km:0.25,estimated_time_mins:12,traffic_delay_seconds:240,traffic_eta_status:"TRAFFIC_ADJUSTED",overall_risk:"CRITICAL",route_status:"NO_SAFE_ROUTE",is_recommended:false,is_fastest:true,critical_segments_count:1,moderate_segments_count:0,unknown_segments_count:0,segments:[segment],geojson_path:geometry,alternative_routes:[],explanation:"CI contract fixture: no safe route",evidence_coverage:"PARTIAL",traffic_status:"CLOSED",is_live_traffic:true,traffic_coverage_ratio:0.6};
  await page.route("**/api/v1/routes/search", route => route.fulfill({json:result}));
  await page.route("**/style.json", route => route.fulfill({json:{version:8,sources:{},layers:[{id:"background",type:"background",paint:{"background-color":"#eeeeee"}}]}}));
  await page.goto("/di-duong?origin=10.7725,106.6980&destination=10.7950,106.7218");
  await page.getByRole("button", {name:"Tìm tuyến đường",exact:true}).click();
  await expect(page.getByText(/Chưa tìm được tuyến tránh nguy hiểm\./)).toBeVisible();
  await expect(page.getByText("Thời gian trên đã tính khoảng 4 phút chậm do xe đông.", {exact:true})).toBeVisible();
  await expect(page.getByText("Có thông tin tốc độ trên khoảng 60% quãng đường; phần còn lại là ước tính.", {exact:true})).toBeVisible();
  await expect(page.getByText(/Cơ sở đô thị|hiệu chuẩn đô thị|ùn tắc quan trắc/)).toHaveCount(0);
  await expect(page.getByText("Đề xuất SafePath", {exact:true})).toHaveCount(0);
  await expect(page.getByText("Đề xuất an toàn", {exact:true})).toHaveCount(0);
  result.traffic_delay_seconds = 0;
  await page.reload();
  await page.getByRole("button", {name:"Tìm tuyến đường",exact:true}).click();
  await expect(page.getByText("Thời gian dự kiến đã tính theo tốc độ giao thông cập nhật.", {exact:true})).toBeVisible();
  await expect(page.getByText(/chưa có tốc độ giao thông cập nhật trên tuyến/)).toHaveCount(0);

});
