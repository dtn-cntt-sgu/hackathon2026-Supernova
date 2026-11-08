import { chromium } from 'playwright';
import { writeFile } from 'node:fs/promises';
const browser = await chromium.launch({headless:true});
const results=[];
for (const viewport of [{width:1440,height:900},{width:390,height:844}]) {
  const page=await browser.newPage({viewport});
  await page.addInitScript(()=>{
    window.__vitals={cls:0,lcp:0,longTasks:0};
    new PerformanceObserver(list=>list.getEntries().forEach(e=>{if(!e.hadRecentInput)window.__vitals.cls+=e.value;})).observe({type:'layout-shift',buffered:true});
    new PerformanceObserver(list=>{const entries=list.getEntries();window.__vitals.lcp=entries[entries.length-1].startTime;}).observe({type:'largest-contentful-paint',buffered:true});
    new PerformanceObserver(list=>{window.__vitals.longTasks+=list.getEntries().length;}).observe({type:'longtask',buffered:true});
  });
  await page.goto(process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:3100');
  await page.locator('.observatory-map[data-map-ready="true"]').waitFor({timeout:30000});
  await page.waitForTimeout(2500);
  const initial=await page.evaluate(()=>({...window.__vitals,canvasCount:document.querySelectorAll('.observatory-map canvas').length}));
  // rAF pacing is a main-thread proxy, not proof of rendered GPU FPS.
  const intervals=await page.evaluate(()=>new Promise(resolve=>{let previous=performance.now();const samples=[];function tick(now){samples.push(now-previous);previous=now;if(samples.length<90)requestAnimationFrame(tick);else resolve(samples);}requestAnimationFrame(tick); document.getElementById('vision').scrollIntoView({behavior:'smooth'});}));
  for(const index of [3,1,2,0,3,0]) {await page.locator('.chapter-nav button').nth(index).click();await page.waitForTimeout(250);}
  const final=await page.evaluate(()=>({...window.__vitals,canvasCount:document.querySelectorAll('.observatory-map canvas').length}));
  intervals.sort((a,b)=>a-b);
  results.push({viewport,initial,afterScroll:final,rafMedianMs:intervals[45],rafP95Ms:intervals[85]});
  await page.close();
}
await browser.close();
const report={conditions:'Single local production run per viewport, Chromium headless, no CPU/network throttle. External real API/tiles. Not Lighthouse or a physical mobile device. rAF intervals are not GPU FPS; no long-duration memory audit.',results};
await writeFile('../docs/CINEMATIC_PERFORMANCE.json',JSON.stringify(report,null,2));
console.log(JSON.stringify(report,null,2));
