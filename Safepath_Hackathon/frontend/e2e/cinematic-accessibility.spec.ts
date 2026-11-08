import {test,expect} from '@playwright/test';
test('reduced motion and keyboard remain available',async({page})=>{
  await page.emulateMedia({reducedMotion:'reduce'});await page.goto('/');
  await page.keyboard.press('Tab');
  await expect(page.locator(':focus')).toHaveAttribute('href','/');
  const ring=await page.locator(':focus').evaluate(el=>getComputedStyle(el).outlineStyle);expect(ring).not.toBe('none');
  const animation=await page.locator('h1').evaluate(el=>getComputedStyle(el).animationDuration);expect(parseFloat(animation)).toBeLessThan(.01);
  await page.keyboard.press('End');
  await expect(page.locator('.story-viewport')).toHaveAttribute('data-scene','3');
  await page.locator('.chapter-nav button').first().focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('.story-viewport')).toHaveAttribute('data-scene','0');
  await expect(page.locator('[inert]')).toHaveCount(0);
});

test('camera dialog traps Tab, closes with Escape and restores focus', async ({page}) => {
  await page.goto('/monitor');
  const trigger = page.getByRole('button', {name: /Xem chi tiết/}).first();
  await trigger.click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await expect(dialog).toHaveAttribute('aria-modal','true');
  await page.keyboard.press('Shift+Tab');
  expect(await dialog.evaluate(el=>el.contains(document.activeElement))).toBeTruthy();
  await page.keyboard.press('Tab');
  expect(await dialog.evaluate(el=>el.contains(document.activeElement))).toBeTruthy();
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  await expect(trigger).toBeFocused();
});
