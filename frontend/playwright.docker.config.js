import { defineConfig } from "@playwright/test";

// Reuse the real two-account workflow against already-running Compose services.
// No native development servers, mocks, traces or credential-bearing screenshots.
export default defineConfig({
  testDir: "./e2e",
  timeout: 90000,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: "http://localhost:8080",
    channel: "msedge",
    headless: true,
    viewport: { width: 1440, height: 1000 },
    trace: "off",
    screenshot: "off",
  },
});
