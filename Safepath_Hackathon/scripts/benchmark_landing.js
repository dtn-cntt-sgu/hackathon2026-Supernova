const { chromium } = require('../frontend/node_modules/playwright');

const PORT = process.env.PORT || 3002;

async function runBenchmark(label = "After (V4 - Pearl Aurora & Aceternity)") {
  const browser = await chromium.launch({
    executablePath: '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
    headless: true,
    args: ['--enable-gpu-rasterization', '--disable-features=IsolateOrigins,site-per-process']
  });

  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 }
  });

  const page = await context.newPage();

  // Inject performance observer for long tasks and layout shifts
  await page.addInitScript(() => {
    window.__perfData = {
      longTasks: [],
      layoutShifts: [],
      frameTimes: [],
      lastRafTime: performance.now(),
      fpsSamples: []
    };

    // Track long tasks (> 50ms)
    try {
      const observer = new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          window.__perfData.longTasks.push({
            name: entry.name,
            duration: entry.duration,
            startTime: entry.startTime
          });
        }
      });
      observer.observe({ entryTypes: ['longtask'] });
    } catch (e) {}

    // Track layout shifts
    try {
      const clsObserver = new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          if (!entry.hadRecentInput) {
            window.__perfData.layoutShifts.push({
              value: entry.value,
              startTime: entry.startTime
            });
          }
        }
      });
      clsObserver.observe({ entryTypes: ['layout-shift'] });
    } catch (e) {}

    // Track RAF frame times
    let frameCount = 0;
    let lastTime = performance.now();
    function trackFrame(now) {
      const delta = now - window.__perfData.lastRafTime;
      window.__perfData.lastRafTime = now;
      window.__perfData.frameTimes.push(delta);
      frameCount++;
      if (now - lastTime >= 1000) {
        window.__perfData.fpsSamples.push(frameCount);
        frameCount = 0;
        lastTime = now;
      }
      requestAnimationFrame(trackFrame);
    }
    requestAnimationFrame(trackFrame);
  });

  await page.goto(`http://localhost:${PORT}`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.landing-nav');
  await page.waitForTimeout(1000);

  // 1. Hover Navbar items & record positions
  const navItemRectsBefore = await page.$$eval('.landing-nav button, .landing-nav a', els =>
    els.map(el => {
      const r = el.getBoundingClientRect();
      return { x: r.x, y: r.y, width: r.width, height: r.height };
    })
  );

  // Hover through nav links
  const navButtons = await page.$$('.nav-links button');
  for (const btn of navButtons) {
    await btn.hover();
    await page.waitForTimeout(100);
  }

  const navItemRectsAfter = await page.$$eval('.landing-nav button, .landing-nav a', els =>
    els.map(el => {
      const r = el.getBoundingClientRect();
      return { x: r.x, y: r.y, width: r.width, height: r.height };
    })
  );

  let maxNavShift = 0;
  for (let i = 0; i < navItemRectsBefore.length; i++) {
    const dx = Math.abs(navItemRectsBefore[i].x - navItemRectsAfter[i].x);
    if (dx > maxNavShift) maxNavShift = dx;
  }

  // 2. Click through ACTs 01 -> 02 -> 03 -> 04
  const chapterButtons = await page.$$('.chapter-nav button');
  for (let i = 0; i < chapterButtons.length; i++) {
    await chapterButtons[i].click();
    await page.waitForTimeout(600);
  }

  // 3. Scroll Down smoothly (ACT 01 -> 04)
  for (let scrollY = 0; scrollY <= 3000; scrollY += 150) {
    await page.evaluate((y) => window.scrollTo(0, y), scrollY);
    await page.waitForTimeout(40);
  }

  // 4. Scroll Up smoothly (ACT 04 -> 01)
  for (let scrollY = 3000; scrollY >= 0; scrollY -= 150) {
    await page.evaluate((y) => window.scrollTo(0, y), scrollY);
    await page.waitForTimeout(40);
  }

  // 5. Hover Liquid Glass Cards
  const cards = await page.$$('.liquid-glass');
  for (const card of cards.slice(0, 4)) {
    try {
      await card.hover();
      await page.waitForTimeout(150);
    } catch (e) {}
  }

  await page.waitForTimeout(500);

  // Collect performance stats
  const perfResults = await page.evaluate(() => {
    const times = window.__perfData.frameTimes.slice(20); // skip initial load frames
    times.sort((a, b) => a - b);
    const p50 = times[Math.floor(times.length * 0.5)] || 16.6;
    const p95 = times[Math.floor(times.length * 0.95)] || 16.6;
    const avgDelta = times.reduce((a, b) => a + b, 0) / (times.length || 1);
    const avgFps = 1000 / avgDelta;

    const totalCls = window.__perfData.layoutShifts.reduce((acc, curr) => acc + curr.value, 0);
    const longTaskCount = window.__perfData.longTasks.length;
    const totalLongTaskDuration = window.__perfData.longTasks.reduce((acc, curr) => acc + curr.duration, 0);

    let jsHeapUsedMB = 0;
    if (performance.memory) {
      jsHeapUsedMB = performance.memory.usedJSHeapSize / (1024 * 1024);
    }

    return {
      totalFrames: times.length,
      avgFps: avgFps.toFixed(1),
      frameTimeP50: p50.toFixed(2),
      frameTimeP95: p95.toFixed(2),
      longTaskCount,
      totalLongTaskDuration: totalLongTaskDuration.toFixed(1),
      totalCls: totalCls.toFixed(4),
      jsHeapUsedMB: jsHeapUsedMB.toFixed(2)
    };
  });

  await browser.close();

  // Mobile test
  const mobileBrowser = await chromium.launch({
    executablePath: '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
    headless: true
  });
  const mobileContext = await mobileBrowser.newContext({
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true
  });
  const mobilePage = await mobileContext.newPage();
  await mobilePage.goto(`http://localhost:${PORT}`, { waitUntil: 'domcontentloaded' });
  await mobilePage.waitForSelector('.landing-nav');
  await mobilePage.waitForTimeout(800);

  // Check horizontal overflow
  const overflow = await mobilePage.evaluate(() => {
    return {
      bodyScrollWidth: document.body.scrollWidth,
      windowInnerWidth: window.innerWidth,
      hasHorizontalOverflow: document.body.scrollWidth > window.innerWidth
    };
  });

  await mobileBrowser.close();

  return {
    label,
    ...perfResults,
    maxNavShift: maxNavShift.toFixed(2),
    mobileOverflow: overflow
  };
}

runBenchmark("Current Baseline (Before)").then((res) => {
  console.log("=== BENCHMARK REPORT ===");
  console.log(JSON.stringify(res, null, 2));
}).catch(console.error);
