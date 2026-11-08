const { chromium } = require('../frontend/node_modules/playwright');
const path = require('path');
const fs = require('fs');

async function capture() {
  const outputDir = path.join(__dirname, '../artifacts/screenshots');
  if (!fs.existsSync(outputDir)) {
    fs.mkdirSync(outputDir, { recursive: true });
  }

  const browser = await chromium.launch({
    executablePath: '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
    headless: true,
    args: ['--enable-gpu-rasterization']
  });

  const viewports = [
    { name: 'desktop_1440', width: 1440, height: 900, isMobile: false },
    { name: 'tablet_768', width: 768, height: 1024, isMobile: false },
    { name: 'mobile_390', width: 390, height: 844, isMobile: true },
    { name: 'mobile_360', width: 360, height: 740, isMobile: true },
    { name: 'mobile_320', width: 320, height: 640, isMobile: true }
  ];

  const results = [];

  for (const vp of viewports) {
    const context = await browser.newContext({
      viewport: { width: vp.width, height: vp.height },
      isMobile: vp.isMobile,
      hasTouch: vp.isMobile
    });
    const page = await context.newPage();
    await page.goto('http://localhost:3002', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.landing-nav');
    await page.waitForTimeout(1000);

    // Check overflow
    const overflow = await page.evaluate(() => ({
      bodyScrollWidth: document.body.scrollWidth,
      windowInnerWidth: window.innerWidth,
      hasOverflow: document.body.scrollWidth > window.innerWidth
    }));

    // Capture Act 1 (Hero)
    const heroFile = path.join(outputDir, `${vp.name}_act01_hero.png`);
    await page.screenshot({ path: heroFile });

    // Scroll to Act 2 (Vision)
    await page.evaluate(() => {
      const el = document.getElementById('vision');
      if (el) el.scrollIntoView({ behavior: 'instant' });
    });
    await page.waitForTimeout(600);
    const visionFile = path.join(outputDir, `${vp.name}_act02_vision.png`);
    await page.screenshot({ path: visionFile });

    // Scroll to Act 3 (News)
    await page.evaluate(() => {
      const el = document.getElementById('news');
      if (el) el.scrollIntoView({ behavior: 'instant' });
    });
    await page.waitForTimeout(600);
    const newsFile = path.join(outputDir, `${vp.name}_act03_news.png`);
    await page.screenshot({ path: newsFile });

    // Scroll to Act 4 (Routing)
    await page.evaluate(() => {
      const el = document.getElementById('routing');
      if (el) el.scrollIntoView({ behavior: 'instant' });
    });
    await page.waitForTimeout(600);
    const routingFile = path.join(outputDir, `${vp.name}_act04_routing.png`);
    await page.screenshot({ path: routingFile });

    results.push({
      viewport: vp.name,
      width: vp.width,
      overflow: overflow.hasOverflow ? 'FAIL (Overflow)' : 'PASS (No Overflow)',
      bodyScrollWidth: overflow.bodyScrollWidth,
      windowInnerWidth: overflow.windowInnerWidth
    });

    await context.close();
  }

  await browser.close();
  console.log("=== VIEWPORT COMPLIANCE REPORT ===");
  console.log(JSON.stringify(results, null, 2));
}

capture().catch(console.error);

