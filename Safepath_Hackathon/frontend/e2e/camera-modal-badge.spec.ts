import { test, expect } from "@playwright/test";

// Live UI regression: no intercepted API or fabricated camera frame.
for (const width of [1280, 375]) {
  test(`Monitor original camera modal at ${width}px`, async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("safepath_onboarding_completed", "true"));
    await page.setViewportSize({ width, height: 800 });
    const forbidden: string[] = [];
    page.on("request", request => {
      if (/type=(analyzed|enhanced)|\/inference|\/vision/.test(request.url())) forbidden.push(request.url());
    });
    await page.goto("/monitor");
    const card = page.getByTestId("camera-card").first();
    await expect(card).toBeVisible({ timeout: 15000 });
    await card.click();
    const modal = page.getByTestId("camera-proxy-modal");
    await expect(modal).toBeVisible();
    await expect(modal).toContainText("Ảnh camera gốc");
    await expect(modal).toContainText("Nguồn:");
    await expect(modal.getByRole("button", { name: /Enhanced|Analyzed|Overlay|tăng cường/ })).toHaveCount(0);
    await expect(page.getByText("AI+", { exact: true })).toHaveCount(0);
    const refresh = page.waitForRequest(request => /\/cameras\/[^/]+\/proxy/.test(request.url()));
    await modal.getByRole("button", { name: "Tải lại ảnh" }).click();
    await refresh;
    expect(await modal.evaluate(element => element.scrollWidth <= element.clientWidth)).toBeTruthy();
    await page.keyboard.press("Escape");
    await expect(modal).not.toBeVisible();
    await expect(card).toBeFocused();
    expect(forbidden).toEqual([]);
  });
}

test("Vietmap snapshot renders through SafePath proxy with source attribution", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("safepath_onboarding_completed", "true"));
  const forbidden: string[] = [];
  page.on("request", request => {
    if (/type=(analyzed|enhanced)|\/inference|\/vision/.test(request.url())) forbidden.push(request.url());
  });
  await page.goto("/monitor");
  await page.getByPlaceholder("Tìm camera theo tên đường, mã hoặc quận...").fill("ITS 8.51");
  const cards = page.getByTestId("camera-card");
  await expect(cards.first()).toBeVisible();
  const image = cards.first().locator("img");
  await expect(image).toBeVisible({ timeout: 20000 });
  await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth)).toBeGreaterThan(0);
  await expect(cards.first()).toContainText("Nguồn: Vietmap CDN");
  expect(forbidden).toEqual([]);
});
