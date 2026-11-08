import {test,expect} from '@playwright/test';
test('actual API values, loaded glass and one geographic context', async ({page}) => {
  const summaryResponse=page.waitForResponse(r=>r.url().endsWith('/api/v1/cameras/summary'));
  await page.goto('/');
  const response=await summaryResponse; expect(response.ok()).toBeTruthy();
  const summary=await response.json();
  await expect(page.getByTestId('network-count')).toHaveText(String(summary.total_registered));
  await expect(page.getByTestId('recent-image-count')).toHaveText(String(summary.valid_images_count));
  const blur=await page.locator('.hero-signal').evaluate(el=>getComputedStyle(el).backdropFilter);
  expect(blur).toContain('blur');
  await expect(page.locator('.observatory-map canvas')).toHaveCount(1);
  await expect(page.locator('.observatory-map')).toHaveAttribute('data-map-ready','true',{timeout:30000});
  await expect(page.locator('.observatory-map')).toHaveAttribute('data-map-failed','false');
  await expect(page.locator('body')).not.toContainText(/Mô phỏng so sánh|Không còn nỗi lo ngập|GPS chính xác/);
});
test('missing values remain explicit and rain zero needs a source',async({page})=>{
  const weatherResponse=page.waitForResponse(r=>r.url().endsWith('/api/v1/weather-tide'));
  await page.goto('/');
  const weather=await(await weatherResponse).json();
  const stats=page.locator('.hero-bottom');
  if(weather.rain_mm_per_hour == null) await expect(stats).toContainText(/Chưa có dữ liệu|Dữ liệu cũ/);
  await expect(page.locator('.route-ready')).toContainText('Có tuyến đường không có nghĩa');
});

test('real offline refresh exposes missing data without invented zero',async({page,context})=>{
  await page.goto('/');
  await expect(page.getByTestId('network-count')).toHaveText(/^\d+$/);
  await context.setOffline(true);
  try {
    await page.getByRole('button',{name:'Cập nhật dữ liệu',exact:true}).click();
    await expect(page.locator('.observatory-error')).toBeVisible();
    await expect(page.locator('.hero-bottom')).toContainText('Chưa có dữ liệu');
    await expect(page.getByTestId('network-count')).toHaveText('—');
  } finally { await context.setOffline(false); }
});
