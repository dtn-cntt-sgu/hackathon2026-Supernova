import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

// Read the measured bundle on disk; never replace API responses with a fixture.
const summary = JSON.parse(readFileSync(resolve("public/benchmark/summary.json"), "utf8"));

test("published dashboard serves the actual measured evidence on desktop and mobile", async ({ page, request }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.addInitScript(() => localStorage.setItem("safepath_tour_state_v1", JSON.stringify({ version: "v1", status: "skipped", updatedAt: new Date().toISOString() })));
  await page.setViewportSize({ width: 1440, height: 1080 });
  await page.goto("/benchmark");
  await expect(page.getByRole("heading", { name: "AI làm được gì?" })).toBeVisible();
  await expect(page.getByText(summary.run_id, { exact: true })).toBeVisible();
  for (const [name, data] of Object.entries(summary.sections)) {
    await expect(page.locator(`#${name}`)).toContainText((data as { status: string }).status);
  }
  for (const model of Object.values(summary.models)) {
    await expect(page.getByRole("table")).toContainText((model as { sha256: string }).sha256);
  }
  await expect(page.locator("#inference").getByRole("figure")).toBeVisible();
  await expect(page.getByRole("link", { name: "commands.json", exact: true })).toHaveAttribute("href", "/benchmark/commands.json");
  await expect(page.locator("#flood img, #vehicle img")).toHaveCount(0);
  for (const artifact of summary.artifacts) {
    const response = await request.get(artifact.href);
    expect(response.ok(), artifact.name).toBe(true);
  }
  const served = await request.get("/benchmark/summary.json");
  expect((await served.json()).run_id).toBe(summary.run_id);
  await page.screenshot({ path: "/tmp/safepath-benchmark-actual-desktop.png" });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.setViewportSize({ width: 375, height: 812 });
  await page.screenshot({ path: "/tmp/safepath-benchmark-actual-mobile.png" });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.getByRole("link", { name: "Khả năng phục vụ", exact: true }).click();
  await expect(page.locator("#load")).toBeInViewport();
  expect(errors).toEqual([]);
});
