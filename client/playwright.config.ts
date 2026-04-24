import { defineConfig, devices } from "@playwright/test";

// Port is pinned in package.json's `dev:e2e` script. Override the base URL
// via PLAYWRIGHT_BASE_URL (typically together with PLAYWRIGHT_SKIP_WEBSERVER)
// when pointing at a pre-running server.
const BASE_URL = process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:5173";
const IS_CI = !!process.env.CI;

export default defineConfig({
  testDir: "./e2e",
  testMatch: /.*\.spec\.ts$/,
  timeout: 30_000,
  expect: { timeout: 10_000 },

  fullyParallel: true,
  forbidOnly: IS_CI,
  retries: IS_CI ? 2 : 0,
  workers: IS_CI ? 2 : undefined,

  reporter: IS_CI
    ? [["github"], ["html", { open: "never", outputFolder: "playwright-report" }], ["list"]]
    : [["list"], ["html", { open: "on-failure", outputFolder: "playwright-report" }]],

  outputDir: "./test-results",

  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    actionTimeout: 10_000,
    navigationTimeout: 15_000,
    extraHTTPHeaders: {
      // Identify Playwright traffic in dev-server logs.
      "X-Playwright": "1",
    },
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],

  webServer: process.env.PLAYWRIGHT_SKIP_WEBSERVER
    ? undefined
    : {
        command: "npm run dev:e2e",
        url: BASE_URL,
        reuseExistingServer: !IS_CI,
        timeout: 120_000,
        stdout: "pipe",
        stderr: "pipe",
      },
});
