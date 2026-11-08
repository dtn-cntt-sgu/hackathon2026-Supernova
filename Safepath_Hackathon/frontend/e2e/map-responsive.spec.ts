import { test, expect } from "@playwright/test";

const routeUrl = "/di-duong?origin=10.7725,106.6980&destination=10.7950,106.7218&originName=Ben%20Thanh&destinationName=Landmark%2081";

for (const width of [375, 390, 768, 900]) {
  test(`map controls and route sheet remain usable at ${width}px`, async ({ page }) => {
    test.setTimeout(60000);
    await page.setViewportSize({ width, height: 850 });
    await page.addInitScript(() => localStorage.setItem("safepath_tour_state_v1", JSON.stringify({ version: "v1", status: "skipped", updatedAt: new Date().toISOString() })));
    await page.goto(routeUrl);
    await expect(page.getByTestId("map-header")).toBeVisible();
    await expect(page.getByRole("button", { name: "Thông tin quan trắc và giải thích tuyến" })).toHaveCount(0);
    if (width < 768) await page.getByRole("button", { name: "Mở bảng tuyến đường", exact: true }).click();
    const search = page.getByRole("button", { name: "Tìm tuyến đường", exact: true });
    await search.scrollIntoViewIfNeeded();
    await expect(search).toBeVisible();
    expect(await search.evaluate(element => {
      const r = element.getBoundingClientRect();
      const top = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
      return Boolean(top && element.contains(top));
    })).toBeTruthy();
    const weather = page.getByTestId("environment-widget");
    await weather.scrollIntoViewIfNeeded();
    expect(await weather.evaluate(element => element.scrollWidth <= element.clientWidth)).toBeTruthy();
    const bounds = await page.evaluate(() => {
      const head = document.querySelector("[data-testid='map-header']")!.getBoundingClientRect();
      const sheet = document.querySelector(".floating-navigator")!.getBoundingClientRect();
      return { headerBottom: head.bottom, sheetTop: sheet.top, sheetBottom: sheet.bottom, height: innerHeight, overflow: document.documentElement.scrollWidth > innerWidth };
    });
    expect(bounds.overflow).toBeFalsy();
    expect(bounds.sheetTop).toBeGreaterThan(bounds.headerBottom);
    expect(bounds.sheetBottom).toBeLessThanOrEqual(bounds.height);
    await search.scrollIntoViewIfNeeded();
    await search.click();
    // Use the real route API; unavailable routing must fail this acceptance check.
    await expect(page.getByTestId("traffic-legend")).toBeVisible({ timeout: 45000 });
    if (width < 768) {
      const start = page.getByRole("button", { name: "Bắt đầu chỉ đường", exact: true });
      await expect(start).toBeVisible();
      const boxes = await page.evaluate(() => {
        const sheet = document.querySelector(".floating-navigator")!.getBoundingClientRect();
        const legend = document.querySelector("[data-testid='traffic-legend']")!.getBoundingClientRect();
        return { sheetTop: sheet.top, legendBottom: legend.bottom };
      });
      expect(boxes.legendBottom).toBeLessThan(boxes.sheetTop);
      expect(await start.evaluate(element => {
        const r = element.getBoundingClientRect();
        const top = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
        return Boolean(top && element.contains(top));
      })).toBeTruthy();
    }
    if (width === 375 || width === 900) await page.screenshot({ path: `/tmp/safepath-fixed-${width}.png` });
  });
}

test("Monitor metadata sits below the image and hides internal source status", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 850 });
  await page.addInitScript(() => localStorage.setItem("safepath_tour_state_v1", JSON.stringify({ version: "v1", status: "skipped", updatedAt: new Date().toISOString() })));
  await page.goto("/monitor");
  await page.getByPlaceholder("Tìm camera theo tên đường, mã hoặc quận...").fill("ITS 8.51");
  const card = page.getByTestId("camera-card").first();
  await card.scrollIntoViewIfNeeded();
  await expect(card.locator("img")).toBeVisible({ timeout: 20000 });
  await expect(card).not.toContainText("RECENTLY_RETRIEVED_CAPTURE_UNKNOWN");
  await expect(card).toContainText("Thời gian ảnh (nhận lúc)");
  await expect(card.getByText("Nguồn: Vietmap CDN", { exact: true })).toHaveCount(1);
  await expect(card).not.toContainText("STALE");
  expect(await card.evaluate(element => {
    const image = element.querySelector("img")!.getBoundingClientRect();
    const metadata = element.querySelector("[role='status']")!.getBoundingClientRect();
    return image.bottom <= metadata.top + 1;
  })).toBeTruthy();
});


test("compact map menu keeps navigation available on tablet", async ({ page }) => {
  await page.setViewportSize({ width: 1100, height: 850 });
  await page.addInitScript(() => localStorage.setItem("safepath_tour_state_v1", JSON.stringify({ version: "v1", status: "skipped", updatedAt: new Date().toISOString() })));
  await page.goto("/di-duong");
  await page.getByLabel("Mở menu điều hướng", { exact: true }).click();
  const menu = page.getByRole("navigation", { name: "Điều hướng ứng dụng", exact: true });
  await expect(menu.getByRole("link", { name: "Quan trắc Camera" })).toBeVisible();
  await expect(menu.getByRole("link", { name: "Bản tin giao thông" })).toBeVisible();
  await expect(menu.getByRole("link", { name: "Bảng điều khiển" })).toBeVisible();
});
