import { test, expect } from "@playwright/test";

test("landing selection analyzes the chosen frame instead of displaying a legacy overlay", async ({page})=>{
  test.setTimeout(90000);
  await page.addInitScript(()=>localStorage.setItem("safepath_tour_state_v1",JSON.stringify({version:"v1",status:"skipped"})));
  const requests:string[]=[];
  page.on("request",request=>{if(request.method()==="POST"&&request.url().includes("/analysis"))requests.push(request.url());});
  await page.goto("/");
  await page.getByRole("button",{name:"02 Nguy cơ ngập",exact:true}).click();
  const selector=page.getByLabel("Chọn camera quan trắc");
  await expect(selector).toBeEnabled();
  expect(requests).toEqual([]);
  const prepared=page.waitForResponse(response=>response.request().method()==="POST"&&response.url().includes("/cameras/5deb576d1dc17d7c5515ad1a/analysis"));
  await selector.selectOption("5deb576d1dc17d7c5515ad1a");
  const analysis=await (await prepared).json();
  expect(analysis.status).toBe("READY");
  const overlay=page.getByRole("img",{name:/Phân tích phương tiện/});
  await expect(overlay).toHaveAttribute("src",new RegExp(analysis.snapshot_id),{timeout:45000});
  await expect.poll(()=>overlay.evaluate((element:HTMLImageElement)=>element.naturalWidth)).toBeGreaterThan(0);
  await expect(page.getByTestId("observed-vehicle-count")).toContainText(String(analysis.vehicle_count));
  const original=page.getByRole("img",{name:/Ảnh gốc/});
  await expect(original).toHaveAttribute("src",new RegExp(analysis.snapshot_id));
  await expect(page.locator("#vision")).not.toContainText("TEST FRAME");
});

test("news omits the technical coordinate badge",async({page})=>{
  await page.goto("/news");
  await expect(page.getByText("Zero-Mock: Không bịa tọa độ",{exact:true})).toHaveCount(0);
});
