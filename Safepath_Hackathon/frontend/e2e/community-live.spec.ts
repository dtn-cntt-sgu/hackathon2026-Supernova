import { test, expect } from "@playwright/test";
import { encode } from "next-auth/jwt";

test("authenticated report persists and anonymous moderation is rejected", async ({ page, context }) => {
  const secret = process.env.SAFEPATH_E2E_AUTH_SECRET;
  test.skip(!secret, "Requires isolated local QA server/session secret; never use production");
  const suffix = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const token = await encode({secret:secret!, token:{email:`report-${suffix}@example.com`, name:"QA report user", providerAccountId:`qa-report-${suffix}`, id:`qa-report-${suffix}`}, maxAge:600});
  const base = new URL(test.info().project.use.baseURL as string);
  await context.addCookies([{name:"next-auth.session-token", value:token, domain:base.hostname, path:"/", httpOnly:true, sameSite:"Lax", secure:false}]);
  await page.addInitScript(() => localStorage.setItem("safepath_tour_state_v1", JSON.stringify({version:"v1",status:"skipped",updatedAt:new Date().toISOString()})));
  await page.goto("/dashboard");
  const location = page.getByRole("combobox", {name:"Vị trí sự cố"});
  await expect(location).toBeVisible();
  await location.fill("10.77012, 106.70012");
  await page.getByRole("option").filter({hasText:"10.77012"}).first().click();
  const description = `Road obstruction observed by QA ${suffix}`;
  await page.getByLabel("Mô tả quan sát hiện tại").fill(description);
  await page.getByRole("button", {name:"Gửi báo cáo", exact:true}).click();
  await expect(page.getByRole("status").filter({hasText:"Đã lưu báo cáo"})).toBeVisible();
  await page.reload();
  await expect(page.getByText(description, {exact:true})).toBeVisible();
  await expect(page.getByText("Chờ xác minh", {exact:true})).toBeVisible();
  expect((await page.request.get("/api/v1/admin/incidents")).status()).toBe(401);
});
