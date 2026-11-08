import { test, expect } from "@playwright/test";

// UI contract fixtures only; they do not prove live benchmark or model accuracy.
const fixture = {
  schema_version: 1, run_id: "ui-contract-fixture", generated_at: "2026-11-08T06:00:00+07:00",
  commit_sha: "fixture-commit", dirty_worktree: true, mode: "offline",
  disclaimer: "UI contract fixture — not a measured benchmark result.",
  models: { vehicle_detector: { architecture: "FixtureSSD", version: "fixture-v1", sha256: "fixture-model-hash" } },
  sections: {
    flood: { status: "NOT EVALUATED", reason: "No independent ground truth", global_iou: null },
    vehicle: { status: "LIMITED", reason: "Counts are not accuracy", model_version: "fixture-detector", sample_count: 2 },
    inference: { status: "VERIFIED", models: { vehicle_detector: { pipeline_p95_ms: 20, runs: [{ run: 1, timings: { pipeline_file: { p50_ms: 10, p95_ms: 20, p99_ms: 30 } } }] } }, provider: "FixtureCPU" },
    routing: { status: "LIMITED", passed: 3, total: 3 },
    camera: { status: "BLOCKED", reason: "Permission not verified" },
    load: { status: "NOT EVALUATED", reason: "No load run" },
  },
  artifacts: [
    { name: "summary.json", href: "/benchmark/summary.json" },
    { name: "benchmark_results.csv", href: "/benchmark/benchmark_results.csv" },
    { name: "flood_predictions.csv", href: "/benchmark/flood_predictions.csv" },
    { name: "limitations.md", href: "https://untrusted.invalid/limitations.md" },
    { name: "private.jpg", href: "/benchmark/private.jpg" },
  ],
};

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("safepath_tour_state_v1", JSON.stringify({ version: "v1", status: "skipped", updatedAt: new Date().toISOString() })));
});

test("benchmark UI contract renders measured values and separates missing accuracy", async ({ page }) => {
  const writes: string[] = [];
  page.on("request", request => { if (request.method() === "POST" && request.url().includes("benchmark")) writes.push(request.url()); });
  await page.route("**/benchmark/summary.json", route => route.fulfill({ json: fixture }));
  await page.goto("/benchmark");
  await expect(page.getByRole("heading", { name: "AI làm được gì?" })).toBeVisible();
  await expect(page.getByText(fixture.disclaimer)).toBeVisible();
  await expect(page.locator("#flood")).toContainText("Chưa có số đo");
  await expect(page.locator("#vehicle")).toContainText("fixture-detector");
  await expect(page.locator("#inference").getByRole("figure")).toContainText("30");
  await expect(page.getByRole("table")).toContainText("fixture-model-hash");
  await expect(page.getByRole("link", { name: "benchmark_results.csv" })).toHaveAttribute("href", "/benchmark/benchmark_results.csv");
  await expect(page.getByRole("link", { name: "flood_predictions.csv", exact: true })).toHaveAttribute("href", "/benchmark/flood_predictions.csv");
  await expect(page.getByRole("link", { name: "limitations.md" })).toHaveCount(0);
  await expect(page.locator('img[src*="private.jpg"]')).toHaveCount(0);
  await expect(page.getByRole("button", { name: /run|chạy/i })).toHaveCount(0);
  expect(writes).toEqual([]);
});

test("missing and invalid benchmark bundles fail closed", async ({ page }) => {
  await page.route("**/benchmark/summary.json", route => route.fulfill({ status: 404, body: "missing" }));
  await page.goto("/benchmark");
  await expect(page.getByRole("status")).toContainText("Chưa tải được báo cáo benchmark hợp lệ");
  await expect(page.getByText("NOT EVALUATED", { exact: true })).toHaveCount(6);
  await page.unroute("**/benchmark/summary.json");
  await page.route("**/benchmark/summary.json", route => route.fulfill({ json: { schema_version: 1, sections: { flood: null } } }));
  await page.reload();
  await expect(page.getByRole("status")).toContainText("Chưa tải được báo cáo benchmark hợp lệ");
  await expect(page.getByText("VERIFIED", { exact: true })).toHaveCount(0);
});

test("benchmark dashboard fits a 375px mobile screen", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.route("**/benchmark/summary.json", route => route.fulfill({ json: fixture }));
  await page.goto("/benchmark");
  await expect(page.getByRole("link", { name: "Về bản đồ" })).toBeVisible();
  await expect(page.getByText(fixture.disclaimer)).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.getByRole("link", { name: "Khả năng phục vụ", exact: true }).click();
  await expect(page.locator("#load")).toBeInViewport();
});


test("ground truth examples require explicit publication permission and an exact manifest link", async ({ page }) => {
  const example = { name: "flood_examples.png", href: "/benchmark/flood_examples.png" };
  const bundle = { ...fixture, sections: { ...fixture.sections, flood: { ...fixture.sections.flood, dataset: { public_examples_authorized: false } } }, artifacts: [...fixture.artifacts, example, { name: "inference_latency.png", href: "/benchmark/inference_latency.png" }] };
  await page.route("**/benchmark/summary.json", route => route.fulfill({ json: bundle }));
  await page.goto("/benchmark");
  await expect(page.getByText(fixture.disclaimer)).toBeVisible();
  await expect(page.locator('img[src="/benchmark/flood_examples.png"]')).toHaveCount(0);
  await expect(page.getByRole("link", { name: "inference_latency.png", exact: true })).toBeVisible();
  bundle.sections.flood.dataset.public_examples_authorized = true;
  await page.reload();
  await expect(page.locator('img[src="/benchmark/flood_examples.png"]')).toHaveCount(1);
  bundle.artifacts = bundle.artifacts.map(item => item.name === example.name ? { ...item, href: "https://untrusted.invalid/flood_examples.png" } : item);
  await page.reload();
  await expect(page.getByText(fixture.disclaimer)).toBeVisible();
  await expect(page.locator('img[src*="flood_examples.png"]')).toHaveCount(0);
});
