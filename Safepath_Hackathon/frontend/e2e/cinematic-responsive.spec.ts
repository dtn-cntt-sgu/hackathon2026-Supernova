import { test, expect } from "@playwright/test";
const sizes = [[1920,1080],[1440,900],[1366,768],[1280,720],[1024,768],[768,1024],[390,844],[375,667]];
for (const [width,height] of sizes) test(`hero flow ${width}x${height}`, async ({page}) => {
  await page.setViewportSize({width,height});
  await page.emulateMedia({reducedMotion: "reduce"});
  const errors: string[] = []; page.on("pageerror", e => errors.push(e.message));
  await page.goto("/");
  await expect(page.locator(".hero-bottom")).toBeVisible();
  const boxes = await page.evaluate(() => {
    const box = (s: string) => { const b = document.querySelector(s)!.getBoundingClientRect(); return {top:b.top,bottom:b.bottom,left:b.left,right:b.right}; };
    return {trust:box('.hero-trust'), stats:box('.hero-bottom'), copy:box('.hero-copy'), signal:box('.hero-signal'), heading:box('h1'), dock:box('.story-bottom'), width:document.documentElement.scrollWidth, viewport:innerWidth, position:getComputedStyle(document.querySelector('.hero-bottom')!).position};
  });
  expect(boxes.position).not.toBe('absolute');
  expect(boxes.stats.top - boxes.trust.bottom).toBeGreaterThanOrEqual(24);
  expect(boxes.width).toBeLessThanOrEqual(boxes.viewport);
  expect(boxes.heading.top).toBeGreaterThan(80);
  expect(boxes.dock.bottom <= boxes.stats.top || boxes.dock.top >= boxes.stats.bottom || boxes.dock.left >= boxes.stats.right || boxes.dock.right <= boxes.stats.left).toBeTruthy();
  expect(boxes.signal.left >= boxes.copy.right || boxes.signal.top >= boxes.copy.bottom).toBeTruthy();
  await expect(page.locator(".observatory-map")).toHaveAttribute("data-map-ready", "true", {timeout:30000});
  const canvas = await page.locator(".observatory-map canvas").boundingBox();
  expect(canvas?.height).toBe(height);
  await page.waitForTimeout(1700);
  await page.screenshot({path:`test-results/cinematic-hero-${width}x${height}.png`});
  await page.screenshot({path:`test-results/cinematic-${width}x${height}.png`,fullPage:true});
  expect(errors).toEqual([]);
});
