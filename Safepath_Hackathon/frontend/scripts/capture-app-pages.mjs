import { chromium } from 'playwright';
import { mkdir, writeFile } from 'node:fs/promises';
const output='../docs/artifacts/cinematic';
await mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true});
const results=[];
for(const width of [1280,390]) {
  const page=await browser.newPage({viewport:{width,height:844}});
  await page.addInitScript(()=>localStorage.setItem('safepath_tour_state_v1',JSON.stringify({version:'v1',status:'skipped',updatedAt:new Date().toISOString()})));
  for(const route of ['map','monitor','news','dashboard','account']) {
    const errors=[];const collect=e=>errors.push(e.message);page.on('pageerror',collect);
    await page.goto(`${process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:3100'}/${route}`);
    await page.waitForTimeout(1500);
    const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
    await page.screenshot({path:`${output}/${route}-${width}.png`});
    results.push({route,width,horizontalOverflow:overflow,unhandledErrors:errors});page.off('pageerror',collect);
  }
  await page.close();
}
await browser.close();
await writeFile(`${output}/app-pages-check.json`,JSON.stringify(results,null,2));
console.log(JSON.stringify(results));
if(results.some(r=>r.horizontalOverflow || r.unhandledErrors.length))process.exitCode=1;
