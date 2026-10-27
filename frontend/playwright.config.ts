import { defineConfig } from "@playwright/test";
import { resolve } from "node:path";

// Browser E2E against the real API serving the built UI, on a throwaway data dir.
// Uses the system Microsoft Edge (channel "msedge"), so no browser download is needed.
const PORT = 8765;
const python = resolve(process.cwd(), "..", "backend", ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");

export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: `http://127.0.0.1:${PORT}`, channel: process.env.E2E_CHANNEL === "chromium" ? undefined : process.env.E2E_CHANNEL || "msedge", trace: "retain-on-failure" },
  webServer: {
    command: `"${python}" -m ledgerline`,
    cwd: "../backend",
    url: `http://127.0.0.1:${PORT}/api/auth/me`,
    timeout: 60_000,
    reuseExistingServer: false,
    env: {
      LEDGERLINE_PORT: String(PORT),
      LEDGERLINE_DATA_DIR: "../frontend/e2e/.data",
      LEDGERLINE_LOG_LEVEL: "WARNING",
    },
  },
});
