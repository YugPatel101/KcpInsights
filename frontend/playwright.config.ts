import { defineConfig, devices } from "@playwright/test";

// Browser end-to-end checks against a running KcpInsights (scripts/dev.sh, or `next start` + the API).
// Uses the installed Google Chrome (channel "chrome"), so no browser download is needed.
// Run: npm run test:e2e   (KCP_E2E_URL overrides the address, default http://localhost:3000)
export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 2,
  reporter: [["list"]],
  use: {
    baseURL: process.env.KCP_E2E_URL ?? "http://localhost:3000",
    channel: "chrome",
    headless: true,
    trace: "off",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], channel: "chrome", viewport: { width: 1440, height: 900 } } },
    { name: "mobile", use: { ...devices["Pixel 7"], channel: "chrome" } },
  ],
});
