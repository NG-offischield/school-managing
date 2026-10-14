import { defineConfig } from "@playwright/test";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

/**
 * End-to-end tests of the portal against a running portal AND the Django
 * backend seeded with `seed_isbree --demo`. The demo password comes from
 * E2E_DEMO_PASSWORD, or from the git-ignored .env.isbree.local at the
 * repository root. The installed Microsoft Edge is used (no browser download).
 */
function demoPassword() {
  if (process.env.E2E_DEMO_PASSWORD) return process.env.E2E_DEMO_PASSWORD;
  const file = resolve(__dirname, "../../.env.isbree.local");
  if (!existsSync(file)) return "";
  const line = readFileSync(file, "utf-8").split(/\r?\n/).find((l) => l.startsWith("ISBREE_DEMO_PASSWORD="));
  return line ? line.slice("ISBREE_DEMO_PASSWORD=".length).trim() : "";
}
process.env.E2E_DEMO_PASSWORD = demoPassword();

export default defineConfig({
  testDir: "tests/e2e",
  timeout: 60_000,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_PORTAL_URL || "http://localhost:3001",
    channel: process.env.E2E_BROWSER_CHANNEL || "msedge",
    locale: "fr-FR",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "desktop", use: { viewport: { width: 1280, height: 800 } } },
    { name: "mobile", use: { viewport: { width: 375, height: 812 }, isMobile: true, hasTouch: true } },
  ],
  webServer: {
    command: "npm run dev",
    url: "http://localhost:3001/connexion",
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
