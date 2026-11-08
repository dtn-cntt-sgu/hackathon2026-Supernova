import { test, expect } from "@playwright/test";

test.describe("P0 Camera Icon Markers & Forensics Acceptance", () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem(
        "safepath_tour_state_v1",
        JSON.stringify({ version: "v1", status: "completed", updatedAt: new Date().toISOString() })
      );
    });
  });

  test("renders camera CCTV icons, clusters, hover tooltips, and truthful modal", async ({
    page,
  }) => {
    // Navigate to map
    await page.goto("/map");

    // 1. Map container and canvas are visible
    await expect(page.locator(".maplibregl-canvas")).toBeVisible({ timeout: 15000 });
    const mapContainer = page.locator("[data-testid='route-map']");
    await expect(mapContainer).toBeVisible();

    // 2. Wait for cameras to load into MapLibre GeoJSON source
    await expect(mapContainer).toHaveAttribute("data-camera-feature-count", /^[1-9]\d*$/, {
      timeout: 15000,
    });

    const count = parseInt((await mapContainer.getAttribute("data-camera-feature-count")) || "0", 10);
    expect(count).toBeGreaterThan(50);

    // 3. Check registered canvas icons on MapLibre instance
    const registeredIcons = await page.evaluate(() => {
      // @ts-ignore
      const map = window.__safepath_map;
      if (!map) return [];
      const expected = [
        "camera-icon-cyan",
        "camera-icon-amber",
        "camera-icon-gray",
        "camera-icon-red",
        "camera-icon-route",
        "camera-cluster-icon",
      ];
      return expected.filter((id) => map.hasImage(id));
    });
    expect(registeredIcons).toContain("camera-icon-cyan");
    expect(registeredIcons).toContain("camera-icon-gray");
    expect(registeredIcons).toContain("camera-cluster-icon");

    // 4. Capture screenshot at initial zoom (Zoom 13 - Clusters active)
    await page.screenshot({ path: "docs/camera_icon_markers_z13.png" });

    // 5. Zoom in to zoom 15 to uncluster
    await page.evaluate(() => {
      // @ts-ignore
      const map = window.__safepath_map;
      if (map) map.setZoom(15.2);
    });
    await page.waitForTimeout(800);

    // Capture screenshot at zoom 15 (Individual camera icons visible)
    await page.screenshot({ path: "docs/camera_icon_markers_z15.png" });

    // 6. Test Hover Tooltip & Click on an unobstructed camera icon
    const hoverPoint = await page.evaluate(() => {
      // @ts-ignore
      const map = window.__safepath_map;
      if (!map) return null;
      const features = map.queryRenderedFeatures({ layers: ["camera-points"] });
      if (!features || features.length === 0) return null;
      const canvasRect = map.getCanvas().getBoundingClientRect();

      // Find first feature in visible, unobstructed map area (right of sidebar at x > 460)
      for (const feat of features) {
        if (feat.geometry.type !== "Point") continue;
        const [lng, lat] = feat.geometry.coordinates;
        const pixel = map.project([lng, lat]);
        const screenX = canvasRect.left + pixel.x;
        const screenY = canvasRect.top + pixel.y;

        if (
          pixel.x > 460 &&
          pixel.x < canvasRect.width - 60 &&
          pixel.y > 100 &&
          pixel.y < canvasRect.height - 100
        ) {
          return {
            x: screenX,
            y: screenY,
            pixelX: pixel.x,
            pixelY: pixel.y,
            name: feat.properties?.name,
            id: feat.properties?.id,
            lng,
            lat,
          };
        }
      }

      // Fallback to first feature
      const [lng, lat] = (features[0].geometry as GeoJSON.Point).coordinates;
      const pixel = map.project([lng, lat]);
      return {
        x: canvasRect.left + pixel.x,
        y: canvasRect.top + pixel.y,
        pixelX: pixel.x,
        pixelY: pixel.y,
        name: features[0].properties?.name,
        id: features[0].properties?.id,
        lng,
        lat,
      };
    });

    if (hoverPoint) {
      // Move mouse with steps to trigger WebGL canvas mousemove events
      await page.mouse.move(hoverPoint.x - 20, hoverPoint.y - 20);
      await page.mouse.move(hoverPoint.x, hoverPoint.y, { steps: 5 });
      await page.waitForTimeout(600);

      // Check if tooltip appeared
      const tooltip = page.locator(".camera-map-tooltip");
      if (!(await tooltip.isVisible())) {
        await page.evaluate((hp) => {
          // @ts-ignore
          const map = window.__safepath_map;
          if (map) {
            map.fire("mousemove", {
              point: { x: hp.pixelX, y: hp.pixelY },
              lngLat: { lng: hp.lng, lat: hp.lat },
              originalEvent: new MouseEvent("mousemove"),
            });
          }
        }, hoverPoint);
        await page.waitForTimeout(400);
      }

      await expect(tooltip).toBeVisible({ timeout: 5000 });
      await page.screenshot({ path: "docs/camera_icon_hover_tooltip.png" });

      // 7. Click camera icon to open modal
      await page.mouse.click(hoverPoint.x, hoverPoint.y);
      await page.waitForTimeout(500);

      const modal = page.locator("[data-testid='camera-evidence-modal']");
      if (!(await modal.isVisible())) {
        // Fallback: fire click directly via MapLibre
        await page.evaluate((hp) => {
          // @ts-ignore
          const map = window.__safepath_map;
          if (map) {
            map.fire("click", {
              point: { x: hp.pixelX, y: hp.pixelY },
              lngLat: { lng: hp.lng, lat: hp.lat },
              originalEvent: new MouseEvent("click"),
            });
          }
        }, hoverPoint);
        await page.waitForTimeout(500);
      }

      // Verify modal opened
      await expect(modal).toBeVisible({ timeout: 5000 });

      // Check header contains camera icon and truthful details
      await expect(modal.locator("svg.lucide-camera")).toBeVisible();
      await expect(modal.getByText(/Truy xuất:/)).toBeVisible();
      await expect(modal.getByText(/Chụp:/)).toBeVisible();

      // Check view toggle tabs
      await expect(modal.getByText("Ảnh gốc (Nguồn)")).toBeVisible();
      await expect(modal.getByText("Ảnh tăng cường (Hỗ trợ AI)")).toBeVisible();
      await expect(modal.getByText("Phát hiện AI (Overlay)")).toBeVisible();

      await page.screenshot({ path: "docs/camera_icon_modal_opened.png" });

      // Close modal
      const closeBtn = modal.getByRole("button", { name: "Đóng chi tiết camera" });
      await closeBtn.click();
      await expect(modal).not.toBeVisible();
    }

    // 8. Test Toggle OFF -> ON
    const cameraSwitch = page.getByRole("switch", { name: "Hiển thị camera" });
    await expect(cameraSwitch).toBeVisible();
    await cameraSwitch.click();
    await expect(cameraSwitch).toHaveAttribute("aria-checked", "false");
    await expect(mapContainer).toHaveAttribute("data-camera-feature-count", "0");

    await cameraSwitch.click();
    await expect(cameraSwitch).toHaveAttribute("aria-checked", "true");
    await expect(mapContainer).toHaveAttribute("data-camera-feature-count", /^[1-9]\d*$/);
  });
});
