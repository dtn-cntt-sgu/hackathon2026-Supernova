import { test, expect } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("safepath_tour_state_v1", JSON.stringify({version:"v1",status:"skipped",updatedAt:new Date().toISOString()})));
});

test("guest authentication and anonymous write rejection are truthful", async ({ page }) => {
  await page.goto("/account");
  await expect(page.getByText("Bạn chưa đăng nhập", { exact:true })).toBeVisible();
  await expect(page.getByText("an.nguyen@example.com",{exact:true})).toHaveCount(0);
  expect((await page.request.get("/api/v1/user/profile", { headers:{"X-User-Id":"spoofed-user"} })).status()).toBe(401);
  expect((await page.request.post("/api/v1/hydrology/ingest",{data:{}})).status()).toBe(401);
  expect((await page.request.get("/api/v1/admin/camera-ingestion/status")).status()).toBe(401);
  expect((await page.request.post("/api/v1/user/sync",{data:{provider:"google",provider_account_id:"spoof",email:"spoof@example.com",display_name:"Spoof"}})).status()).toBe(401);
});

test("real local routing returns source geometry and unknown risk without admitted evidence", async ({ request }) => {
  const response=await request.post("/api/v1/routes/search",{data:{origin:{lat:10.7725,lng:106.698},destination:{lat:10.795,lng:106.7218}}});
  expect(response.status()).toBe(200);
  const data=await response.json();
  for (const route of [data,...data.alternative_routes]) {
    expect(route.geojson_path.coordinates.length).toBeGreaterThan(10);
    expect(route.overall_risk).toBe("UNKNOWN");
    expect(route.route_ai_status).toBe("BLOCKED_BY_EVIDENCE");
    expect(route.segments.every((segment:any)=>segment.risk_level!=="SAFE")).toBeTruthy();
  }
  const ready=await request.get("/api/v1/ready");
  expect(ready.ok()).toBeTruthy();
  const readiness=await ready.json();
  expect(readiness.routing_ready).toBe(true);
  expect(["CURRENT", "NOT_REQUIRED_FOR_DEVELOPMENT"]).toContain(readiness.schema);
  expect(readiness.inference_status).toBe("BLOCKED_BY_PERMISSION");
});

test("Monitor source-image viewing makes no inference request", async ({ page }) => {
  const analysis:string[]=[];
  page.on("request",request=>{if(request.method()==="POST"&&request.url().includes("/analysis")) analysis.push(request.url());});
  await page.goto("/monitor");
  await page.getByPlaceholder("Tìm camera theo tên đường, mã hoặc quận...").fill("ITS 8.51");
  const card=page.getByTestId("camera-card").first();
  await card.scrollIntoViewIfNeeded();
  await expect(card.locator("img")).toBeVisible({timeout:20000});
  await expect.poll(()=>card.locator("img").evaluate((image:HTMLImageElement)=>image.naturalWidth)).toBeGreaterThan(0);
  expect(analysis).toEqual([]);
});
