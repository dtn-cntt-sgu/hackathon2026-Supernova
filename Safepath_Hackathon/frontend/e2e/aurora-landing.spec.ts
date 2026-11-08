import { test, expect } from "@playwright/test";

test.describe("Aceternity Aurora Background Landing Page Verification", () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem("safepath_onboarding_completed", "true");
    });
  });

  test("Desktop: verifies single persistent Aurora background, seamless ACT 01-04 transitions & frame metrics", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/");
    await page.waitForLoadState("networkidle");

    // 1. Verify single Aurora Background instance
    const auroraBgs = page.locator("[class*='[--aurora:']");
    await expect(auroraBgs).toHaveCount(1);
    await expect(auroraBgs).toBeVisible();

    // 2. Verify legacy SVG backgrounds & BackgroundGradientAnimation do NOT exist
    await expect(page.locator("img[src*='act01_smart_city']")).toHaveCount(0);
    await expect(page.locator("img[src*='act02_flood']")).toHaveCount(0);
    await expect(page.locator("img[src*='act03_traffic']")).toHaveCount(0);
    await expect(page.locator("img[src*='act04_smart']")).toHaveCount(0);
    await expect(page.locator(".gradients-container")).toHaveCount(0);

    // 3. Screenshot ACT 01
    await page.screenshot({ path: "docs/act01_aurora_desktop.png" });

    // 4. Transition to ACT 02 (Vision AI / Nguy cơ ngập)
    const act02Btn = page.locator("button:has-text('02 Nguy cơ ngập')");
    await expect(act02Btn).toBeVisible();
    await act02Btn.click();
    await page.waitForTimeout(600);

    // Verify ACT 02 content is visible and screenshot
    const act02Title = page.locator("text=02 / NGUY CƠ TIỀM ẨN DƯỚI MƯA & THỦY TRIỀU");
    await expect(act02Title).toBeVisible();
    await page.screenshot({ path: "docs/act02_aurora_desktop.png" });

    // 5. Transition to ACT 03 (Bản tin giao thông)
    const act03Btn = page.locator("button:has-text('03 Bản tin')");
    await expect(act03Btn).toBeVisible();
    await act03Btn.click();
    await page.waitForTimeout(600);

    // Verify ACT 03 content is visible and screenshot
    const act03Title = page.locator("text=03 / BẢN TIN GIAO THÔNG THÀNH PHỐ");
    await expect(act03Title).toBeVisible();
    await page.screenshot({ path: "docs/act03_aurora_desktop.png" });

    // 6. Transition to ACT 04 (Điều hướng thông minh)
    const act04Btn = page.locator("button:has-text('04 Điều hướng')");
    await expect(act04Btn).toBeVisible();
    await act04Btn.click();
    await page.waitForTimeout(600);

    // Verify ACT 04 content is visible and screenshot
    const act04Title = page.locator("text=04 / ĐỊNH TUYẾN THÔNG MINH");
    await expect(act04Title).toBeVisible();
    await page.screenshot({ path: "docs/act04_aurora_desktop.png" });

    // 7. Rapid navigation jump back: ACT 04 -> ACT 01
    const act01Btn = page.locator("button:has-text('01 Đô thị 3D')");
    await act01Btn.click();
    await page.waitForTimeout(600);

    // Verify Aurora background did NOT remount and remained a single instance
    await expect(auroraBgs).toHaveCount(1);
    await expect(page.locator("text=Tìm lộ trình tránh ngập")).toBeVisible();

    // 8. Performance Frame-Time Sampling during continuous scroll
    const frameMetrics = await page.evaluate(async () => {
      const frameTimes: number[] = [];
      let lastTime = performance.now();

      return new Promise<{ avgFps: number; p95FrameTimeMs: number; droppedFrames: number }>((resolve) => {
        let frameCount = 0;
        const maxFrames = 60; // Sample 60 animation frames (~1 sec)

        const sample = (now: number) => {
          const delta = now - lastTime;
          lastTime = now;
          if (frameCount > 0) {
            frameTimes.push(delta);
          }
          frameCount++;

          // Simulate gentle scroll activity
          window.scrollBy(0, 10);

          if (frameCount < maxFrames) {
            requestAnimationFrame(sample);
          } else {
            const sorted = [...frameTimes].sort((a, b) => a - b);
            const sum = frameTimes.reduce((acc, val) => acc + val, 0);
            const avgMs = sum / frameTimes.length;
            const p95 = sorted[Math.floor(sorted.length * 0.95)] || avgMs;
            const dropped = frameTimes.filter((t) => t > 33.3).length; // >33.3ms drops below 30fps

            resolve({
              avgFps: Math.round(1000 / avgMs),
              p95FrameTimeMs: Math.round(p95 * 10) / 10,
              droppedFrames: dropped,
            });
          }
        };

        requestAnimationFrame(sample);
      });
    });

    console.log("DESKTOP FRAME METRICS:", JSON.stringify(frameMetrics));
    expect(frameMetrics.avgFps).toBeGreaterThanOrEqual(30);
    expect(frameMetrics.p95FrameTimeMs).toBeLessThanOrEqual(60);
  });

  test("Mobile: verifies Aurora background layout & responsiveness across 320px, 360px, 390px, 430px", async ({
    page,
  }) => {
    const viewports = [
      { width: 320, height: 568, name: "320px" },
      { width: 360, height: 740, name: "360px" },
      { width: 390, height: 844, name: "390px" },
      { width: 430, height: 932, name: "430px" },
    ];

    for (const vp of viewports) {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto("/");
      await page.waitForLoadState("networkidle");

      // Verify Aurora is rendered and visible
      const aurora = page.locator("[class*='[--aurora:']");
      await expect(aurora).toBeVisible();

      // Verify no horizontal overflow
      const hasHorizontalScroll = await page.evaluate(() => {
        return document.documentElement.scrollWidth > document.documentElement.clientWidth;
      });
      expect(hasHorizontalScroll).toBe(false);

      if (vp.width === 390) {
        await page.screenshot({ path: "docs/act01_aurora_mobile_390.png" });
      }
    }
  });

  test("Accessibility: verifies prefers-reduced-motion stops animation cleanly", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/");
    await page.waitForLoadState("networkidle");

    const auroraLayer = page.locator("[class*='[--aurora:']");
    await expect(auroraLayer).toBeVisible();

    // Check that animation is none or paused under reduced-motion
    const animationName = await auroraLayer.evaluate((el) => {
      const afterStyle = window.getComputedStyle(el, "::after");
      return afterStyle.animationName;
    });

    console.log("REDUCED MOTION ANIMATION NAME:", animationName);
    // Either 'none' or reduced
    expect(["none", ""].includes(animationName) || animationName.toLowerCase().includes("none")).toBe(true);
  });
});
