import { defineConfig } from "@playwright/test";

// The judge path against a running site, on demand only (never in CI):
//   LIVE_URL=https://35-207-220-110.sslip.io npx playwright test -c playwright.live.config.ts
// Each run presses "Judge demo — one click" exactly once, which creates one practice company on the simulated bank.
export default defineConfig({
  testDir: "e2e-live",
  timeout: 240_000,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: { baseURL: process.env.LIVE_URL || "http://127.0.0.1:8000", channel: process.env.E2E_CHANNEL || "msedge", trace: "off" },
});
