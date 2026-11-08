import {test,expect} from '@playwright/test';
test('chapters recover on reverse scroll; CTA opens real map',async({page})=>{
  await page.emulateMedia({reducedMotion:'reduce'});
  await page.addInitScript(()=>localStorage.setItem('safepath_tour_state_v1',JSON.stringify({version:'v1',status:'skipped',updatedAt:new Date().toISOString()})));
  await page.goto('/');
  for(const index of [1,2,3,2,1,0,3,0]) {
    await page.locator('.chapter-nav button').nth(index).click();
    await expect(page.locator('.story-viewport')).toHaveAttribute('data-scene',String(index));
    await expect(page.locator('.observatory-map canvas')).toHaveCount(1);
  }
  await page.locator('.hero-copy a[href="/map"]').click();
  await expect(page).toHaveURL(/\/map$/);
  await expect(page.getByTestId('origin-combobox')).toBeVisible();
});
for(const width of [1280,390]) for(const route of ['/monitor','/news','/dashboard','/account']) test(`app page ${route} at ${width}`,async({page})=>{
  await page.setViewportSize({width,height:844});
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(()=>localStorage.setItem('safepath_tour_state_v1',JSON.stringify({version:'v1',status:'skipped',updatedAt:new Date().toISOString()})));
  await page.goto(route);await expect(page.locator('header')).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
  const heading=await page.getByRole('heading',{level:1}).first().boundingBox();
  if(heading) expect(heading.y).toBeGreaterThanOrEqual(0);
  await page.screenshot({path:`test-results/app-${route.slice(1)}-${width}.png`});
  expect(errors).toEqual([]);
});

test('landing selections transfer real places into the routing form', async ({page}) => {
  await page.emulateMedia({reducedMotion:'reduce'});
  await page.addInitScript(()=>localStorage.setItem('safepath_tour_state_v1',JSON.stringify({version:'v1',status:'skipped',updatedAt:new Date().toISOString()})));
  await page.goto('/');
  await page.locator('.chapter-nav button').nth(3).click();
  await page.getByRole('combobox',{name:'Điểm đi của hành trình'}).fill('Chợ Bến Thành');
  await page.getByRole('listbox').getByRole('option').first().click();
  await page.getByRole('combobox',{name:'Điểm đến của hành trình'}).fill('Landmark 81');
  await page.getByRole('listbox').getByRole('option').first().click();
  const origin=await page.getByRole('combobox',{name:'Điểm đi của hành trình'}).inputValue();
  const destination=await page.getByRole('combobox',{name:'Điểm đến của hành trình'}).inputValue();
  await page.getByRole('link',{name:'Mở bản đồ hành trình'}).click();
  await expect(page.getByTestId('origin-combobox').getByRole('combobox')).toHaveValue(origin);
  await expect(page.getByTestId('destination-combobox').getByRole('combobox')).toHaveValue(destination);
  await expect(page.getByRole('button',{name:'Tìm tuyến đường',exact:true})).toBeEnabled();
});
