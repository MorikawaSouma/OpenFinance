import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 45_000,
  expect: { timeout: 8_000 },
  // Always run E2E against an isolated Next dev server to avoid stale local processes.
  // This keeps results deterministic even when localhost:3000 is already occupied.
  webServer: {
    command: "npm run dev -- --port 3100",
    url: process.env.E2E_BASE_URL || "http://127.0.0.1:3100/chat",
    timeout: 120_000,
    reuseExistingServer: false,
  },
  use: {
    baseURL: process.env.E2E_BASE_URL || "http://127.0.0.1:3100",
    trace: "on-first-retry",
  },
  reporter: [["list"]],
});
