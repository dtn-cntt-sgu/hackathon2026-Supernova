import { test, expect } from "@playwright/test";
import { createHash } from "node:crypto";

test("camera runs real detection only after selecting Overlay", async ({ page }) => {
  test.setTimeout(60000);
  await page.setViewportSize({ width: 1280, height: 850 });
  await page.addInitScript(() => {
    localStorage.setItem("safepath_tour_state_v1", JSON.stringify({ version: "v1", status: "skipped", updatedAt: new Date().toISOString() }));
    sessionStorage.setItem("safepath.showCameras", "true");
  });
  const camerasResponse = await page.request.get("/api/v1/cameras?limit=1000");
  expect(camerasResponse.ok()).toBeTruthy();
  const camera = (await camerasResponse.json()).find((item: any) => item.cam_id === "5deb576d1dc17d7c5515ad1a");
  expect(camera).toBeTruthy();
  await page.goto("/di-duong");
  await page.waitForFunction(() => Boolean((window as any).__safepath_map?.getLayer("camera-points")));
  await expect(page.locator("[data-camera-feature-count]")).toHaveAttribute("data-camera-feature-count", /^[1-9]\d*$/);
  await page.evaluate(({ lng, lat }) => (window as any).__safepath_map.jumpTo({ center: [lng, lat], zoom: 18, pitch: 0, bearing: 0 }), camera);
  await expect.poll(() => page.evaluate(() => (window as any).__safepath_map.queryRenderedFeatures(undefined, { layers: ["camera-points"] }).length)).toBeGreaterThan(0);
  const point = await page.evaluate(({ lng, lat }) => {
    const p = (window as any).__safepath_map.project([lng, lat]);
    const canvas = document.querySelector(".maplibregl-canvas")!.getBoundingClientRect();
    return { x: canvas.x + p.x, y: canvas.y + p.y };
  }, camera);
  const inferenceRequests: string[] = [];
  page.on("request", request => { if (request.method() === "POST" && request.url().includes("/analysis")) inferenceRequests.push(request.url()); });
  await page.mouse.click(point.x, point.y);
  const modal = page.getByTestId("camera-proxy-modal");
  await expect(modal).toBeVisible();
  const image = modal.getByRole("img");
  await expect(image).toBeVisible({ timeout: 20000 });
  await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth)).toBeGreaterThan(0);
  const refreshed = page.waitForResponse(response => response.url().includes(`/cameras/${camera.cam_id}/proxy`) && response.request().method() === "GET");
  await modal.getByRole("button", { name: "Tải lại ảnh", exact: true }).click();
  expect((await refreshed).ok()).toBeTruthy();
  expect(inferenceRequests).toEqual([]);
  await expect(modal.getByRole("tab", { name: /tăng cường/i })).toHaveCount(0);
  const prepared=page.waitForResponse(response=>response.url().includes(`/cameras/${camera.cam_id}/analysis`)&&response.request().method()==="POST");
  await modal.getByRole("tab",{name:"Phát hiện AI (Overlay)",exact:true}).click();
  let analysis=await (await prepared).json();
  if(analysis.status==="FRAME_CHANGED") {
    const retry=await page.waitForResponse(response=>response.url().includes(`/cameras/${camera.cam_id}/analysis`)&&response.request().method()==="POST");
    analysis=await retry.json();
  }
  await expect(modal.getByRole("img",{name:`Phát hiện AI camera ${camera.name}`,exact:true})).toBeVisible({timeout:45000});
  expect(analysis.status).toBe("READY");
  const overlay=modal.getByRole("img");
  await expect(overlay).toHaveAttribute("src",new RegExp(analysis.snapshot_id));
  await expect.poll(()=>overlay.evaluate((image:HTMLImageElement)=>image.naturalWidth)).toBeGreaterThan(0);
  await expect(modal.getByText("Nguồn: Vietmap CDN",{exact:true})).toHaveCount(1);
  await expect(modal).toContainText("Thời gian ảnh (nhận lúc)");
  await expect(modal).not.toContainText("STALE");
  await modal.getByRole("tab",{name:"Ảnh gốc (Nguồn)",exact:true}).click();
  await expect(modal.getByRole("img")).toHaveAttribute("src",new RegExp(analysis.snapshot_id));
  await modal.getByRole("img").evaluate(async (image:HTMLImageElement)=>await image.decode());
  const sourceResponse=await page.request.get(analysis.image_url);
  expect(sourceResponse.ok()).toBeTruthy();
  expect(createHash("sha256").update(await sourceResponse.body()).digest("hex")).toBe(analysis.content_sha256);
  const overlayResponse=await page.request.get(analysis.overlay_url);
  expect(overlayResponse.headers()["x-inference-input-sha256"]).toBe(analysis.content_sha256);
  expect(await modal.evaluate(element=>element.scrollWidth<=element.clientWidth)).toBeTruthy();
  await page.screenshot({path:"/tmp/safepath-camera-explicit-overlay.png"});
});
