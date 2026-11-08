import { test, expect } from "@playwright/test";

test("a sourced OSRM step can be highlighted without claiming an OSM Way ID", async ({ page }) => {
  await page.goto("/map");
  await page.getByRole("button", { name: "Chợ Bến Thành" }).click();
  await page.getByRole("button", { name: "Ngã tư Hàng Xanh" }).click();
  await page.getByRole("button", { name: /^Tìm tuyến đường/ }).click();
  await expect(page.getByText("Tuyến đang chọn")).toBeVisible({ timeout: 15000 });
  await page.getByRole("button", { name: /^Chỉ đường$/ }).click();
  const stepButton = page.getByRole("button", { name: /^1\./ }).first();
  await expect(stepButton).toBeVisible({ timeout: 15000 });
  await stepButton.click();
  await expect(page.locator("[data-highlight-vertices]")).toHaveAttribute("data-highlight-vertices", /^\d+$/);
  await expect(page.locator("[data-tiles-ready='true']")).toBeVisible();
  await page.screenshot({ path: "../docs/screenshots/phase2-step-highlight.png", fullPage: true });
  await stepButton.click();
  await expect(page.locator("[data-highlight-vertices]")).toHaveCount(0);
});
