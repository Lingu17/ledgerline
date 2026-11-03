import { defineConfig } from "@playwright/test";
import { resolve } from "node:path";

// Browser E2E against the real API serving the built UI, on a throwaway data dir.
// Uses the system Microsoft Edge (channel "msedge"), so no browser download is needed.
const PORT = 8765;
const AGENT_PORT = 8791;  // the reference payer agent (see e2e test "own agent")
const python = resolve(process.cwd(), "..", "backend", ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");

export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: `http://127.0.0.1:${PORT}`, channel: process.env.E2E_CHANNEL === "chromium" ? undefined : process.env.E2E_CHANNEL || "msedge", trace: "retain-on-failure" },
  webServer: [{
    // A customer's own payer agent: the reference agent as a separate process, with its own key.
    command: `"${python}" ../tools/payer_agent/agent.py --port ${AGENT_PORT} --key-file e2e/.data/agent/agent_key.json`,
    port: AGENT_PORT,
    timeout: 60_000,
    reuseExistingServer: false,
  }, {
    command: `"${python}" -m ledgerline`,
    cwd: "../backend",
    url: `http://127.0.0.1:${PORT}/api/auth/me`,
    timeout: 60_000,
    reuseExistingServer: false,
    env: {
      LEDGERLINE_PORT: String(PORT),
      LEDGERLINE_DATA_DIR: "../frontend/e2e/.data",
      LEDGERLINE_LOG_LEVEL: "WARNING",
      // Every test signs up its own company from this one address; the sign-up limit has its own backend tests.
      LEDGERLINE_SIGNUP_PER_IP_HOUR: "100000",
      LEDGERLINE_SIGNUP_PER_IP_DAY: "100000",
      LEDGERLINE_SIGNUP_PER_DAY: "100000",
      // Test only: lets a customer's agent be http://127.0.0.1. The hosted app never sets this.
      LEDGERLINE_PAYER_AGENT_ALLOW_LOOPBACK: "1",
    },
  }],
});
