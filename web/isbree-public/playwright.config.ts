import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests of the public site, against a running site AND the Django
 * backend (docker compose). The installed Microsoft Edge is used (channel
 * "msedge"): no browser download. Set E2E_BROWSER_CHANNEL to change it.
 */
export default defineConfig({
  testDir: "tests/e2e",
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_PUBLIC_URL || "http://localhost:3000",
    channel: process.env.E2E_BROWSER_CHANNEL || "msedge",
    locale: "fr-FR",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Edge"], channel: process.env.E2E_BROWSER_CHANNEL || "msedge" } },
    { name: "mobile", use: { viewport: { width: 375, height: 812 }, isMobile: true, hasTouch: true } },
  ],
  webServer: {
    command: "npm run dev",
    url: "http://localhost:3000",
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
