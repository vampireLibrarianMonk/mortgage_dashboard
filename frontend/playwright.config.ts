import { defineConfig } from "@playwright/test";

// E2E against the always-on local deployment (Caddy -> uvicorn on 9001).
// Run with: npm run e2e (from frontend/) — the app must be running.
export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: "http://app.mortgage-dashboard",
    screenshot: "only-on-failure",
    viewport: { width: 1440, height: 1000 },
  },
});