import { chromium } from '@playwright/test';
import { mkdir } from 'node:fs/promises';

const outputDir = '../docs/screenshots';
await mkdir(outputDir, { recursive: true });

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({
  viewport: { width: 1440, height: 900 },
  deviceScaleFactor: 2,
});

await page.addInitScript(() => {
  localStorage.setItem('safepath_tour_state_v1', JSON.stringify({
    version: 'v1',
    status: 'skipped',
    updatedAt: new Date().toISOString()
  }));
});

const errors = [];
page.on('pageerror', (err) => {
  console.error('[PageError]', err.message);
  errors.push(err.message);
});

console.log('Testing Landing Page (http://localhost:3000/)...');
await page.goto('http://localhost:3000/', { waitUntil: 'networkidle' });
await page.waitForTimeout(2000);

// Verify Liquid Glass on landing nav
const navRefract = await page.evaluate(() => {
  const nav = document.querySelector('.landing-nav');
  const bottom = document.querySelector('.story-bottom');
  return {
    navFound: !!nav,
    navVariant: nav?.getAttribute('data-variant'),
    navRefract: nav?.getAttribute('data-refract'),
    bottomFound: !!bottom,
    bottomVariant: bottom?.getAttribute('data-variant'),
    bottomRefract: bottom?.getAttribute('data-refract'),
  };
});
console.log('Landing Nav refraction inspection:', navRefract);

await page.screenshot({ path: `${outputDir}/liquid_glass_landing_act1.png` });

// Scroll to Act 4
await page.evaluate(() => {
  window.scrollTo({ top: document.body.scrollHeight, behavior: 'instant' });
});
await page.waitForTimeout(1500);
await page.screenshot({ path: `${outputDir}/liquid_glass_landing_act4.png` });

console.log('Testing Map Page (http://localhost:3000/di-duong)...');
await page.goto('http://localhost:3000/di-duong', { waitUntil: 'networkidle' });
await page.waitForTimeout(3000);

// Check GlassToggle and spatial-dock
const mapGlass = await page.evaluate(() => {
  const toggle = document.querySelector('.map-camera-controls [data-variant="button"]');
  const dock = document.querySelector('.spatial-dock[data-variant="pill"]');
  return {
    toggleFound: !!toggle,
    toggleVariant: toggle?.getAttribute('data-variant'),
    toggleRefract: toggle?.getAttribute('data-refract'),
    dockFound: !!dock,
    dockVariant: dock?.getAttribute('data-variant'),
    dockRefract: dock?.getAttribute('data-refract'),
  };
});
console.log('Map elements refraction inspection:', mapGlass);

await page.screenshot({ path: `${outputDir}/liquid_glass_diduong.png` });

// Open camera filter dropdown
console.log('Opening camera filter popover...');
const filterTrigger = await page.$('.map-camera-controls button[aria-label="Lọc loại camera"]');
if (filterTrigger) {
  await filterTrigger.click();
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${outputDir}/liquid_glass_toggle_dropdown.png` });
  console.log('Saved liquid_glass_toggle_dropdown.png');
} else {
  console.log('Camera filter trigger not visible directly, checking toggle switch state...');
}

// Try clicking a camera marker if available
console.log('Searching for camera markers or opening evidence modal...');
const marker = await page.$('.camera-marker, .marker-camera, [data-cam-id]');
if (marker) {
  await marker.click();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${outputDir}/liquid_glass_camera_modal.png` });
  console.log('Saved liquid_glass_camera_modal.png');
} else {
  console.log('No marker found directly on viewport; testing monitor page for modal...');
  await page.goto('http://localhost:3000/monitor', { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);
  const camCard = await page.$('.camera-feed-card, [data-testid="camera-card"], button:has-text("Chi tiết")');
  if (camCard) {
    await camCard.click();
    await page.waitForTimeout(1500);
    await page.screenshot({ path: `${outputDir}/liquid_glass_camera_modal.png` });
    console.log('Saved liquid_glass_camera_modal.png from monitor page');
  }
}

await browser.close();

console.log('Verification finished. Total unhandled errors:', errors.length);
if (errors.length > 0) {
  console.error('Errors encountered:', errors);
  process.exit(1);
}
