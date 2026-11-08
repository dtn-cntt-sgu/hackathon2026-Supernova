const { chromium } = require('../frontend/node_modules/playwright');

async function measureFps() {
  const browser = await chromium.launch({
    executablePath: '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
    headless: true,
    args: ['--enable-gpu-rasterization', '--disable-features=IsolateOrigins,site-per-process']
  });

  const setupContext = async (viewport) => {
    const context = await browser.newContext({
      viewport: { width: viewport.width, height: viewport.height }
    });
    await context.addInitScript(() => {
      try {
        localStorage.setItem(
          "safepath_tour_state_v1",
          JSON.stringify({
            completedTours: ["map", "news", "monitor"],
            dismissedTours: ["map", "news", "monitor"],
            showWelcomeDialog: false
          })
        );
      } catch (e) {}
    });
    return context;
  };

  console.log("=== MEASURING FPS DURING HOVER & SCROLL ===");

  async function recordFps(page, activityFn) {
    await page.evaluate(() => {
      window.__fpsFrames = [];
      window.__fpsActive = true;
      let lastTime = performance.now();
      function tick(time) {
        if (!window.__fpsActive) return;
        const delta = time - lastTime;
        lastTime = time;
        window.__fpsFrames.push(delta);
        requestAnimationFrame(tick);
      }
      requestAnimationFrame(tick);
    });

    await activityFn();

    const fpsResult = await page.evaluate(() => {
      window.__fpsActive = false;
      const frames = window.__fpsFrames || [];
      if (frames.length < 2) return { avgFps: 60, minFps: 60, frameCount: 0 };
      const deltas = frames.slice(1);
      const avgDelta = deltas.reduce((a, b) => a + b, 0) / deltas.length;
      const maxDelta = Math.max(...deltas);
      const avgFps = Math.round(1000 / avgDelta);
      const minFps = Math.round(1000 / maxDelta);
      const longTasks = deltas.filter(d => d > 50).length;
      return { avgFps, minFps, frameCount: deltas.length, longTasks };
    });

    return fpsResult;
  }

  // 1. Landing Page Hover & Scroll FPS
  {
    const context = await setupContext({ width: 1440, height: 900 });
    const page = await context.newPage();
    await page.goto('http://localhost:3002/', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(600);

    const landingFps = await recordFps(page, async () => {
      for (let i = 0; i < 20; i++) {
        await page.mouse.move(200 + i * 20, 300 + (i % 5) * 40);
        await page.evaluate((y) => window.scrollBy(0, y), 30);
        await page.waitForTimeout(50);
      }
    });

    console.log(`Landing Page FPS:`);
    console.log(`  - Average FPS: ${landingFps.avgFps}`);
    console.log(`  - Min FPS: ${landingFps.minFps}`);
    console.log(`  - Long Tasks (>50ms): ${landingFps.longTasks}`);

    await context.close();
  }

  // 2. /di-duong Map Interaction FPS
  {
    const context = await setupContext({ width: 1440, height: 900 });
    const page = await context.newPage();
    await page.goto('http://localhost:3002/di-duong', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.maplibregl-canvas');
    await page.waitForTimeout(800);

    const mapFps = await recordFps(page, async () => {
      await page.mouse.move(700, 500);
      await page.mouse.down();
      for (let i = 0; i < 15; i++) {
        await page.mouse.move(700 + i * 15, 500 + i * 10);
        await page.waitForTimeout(60);
      }
      await page.mouse.up();
    });

    console.log(`/di-duong MapLibre FPS:`);
    console.log(`  - Average FPS: ${mapFps.avgFps}`);
    console.log(`  - Min FPS: ${mapFps.minFps}`);
    console.log(`  - Long Tasks (>50ms): ${mapFps.longTasks}`);

    await context.close();
  }

  await browser.close();
  console.log("=== FPS BENCHMARK COMPLETED ===");
}

measureFps()
  .then(() => process.exit(0))
  .catch(e => {
    console.error(e);
    process.exit(1);
  });
