import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL || "http://127.0.0.1:3100",
    trace: "on-first-retry",
    headless: true,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: process.env.PLAYWRIGHT_EXTERNAL_SERVER ? undefined : {
    command: "PORT=3100 node .next/standalone/server.js",
    port: 3100,
    reuseExistingServer: true,
    env: {
      AUTH_SECRET: "safepath-dev-secret-key-12345678901234567890",
      NEXTAUTH_SECRET: "safepath-dev-secret-key-12345678901234567890",
    },
  },
});
