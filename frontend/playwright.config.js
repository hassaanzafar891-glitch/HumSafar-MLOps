import { defineConfig } from "@playwright/test";
const frontendPort = Number(process.env.HUMSAFAR_E2E_PORT || 5174);
const frontendURL = `http://127.0.0.1:${frontendPort}`;
export default defineConfig({
  testDir: "./e2e",
  timeout: 90000,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: frontendURL,
    channel: "msedge",
    headless: true,
    viewport: { width: 1440, height: 1000 },
    trace: "off",
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      command: "..\\.venv\\Scripts\\python.exe e2e/run_backend.py",
      url: "http://127.0.0.1:8765/health",
      timeout: 60000,
      reuseExistingServer: false,
    },
    {
      command: `npm.cmd run dev -- --port ${frontendPort} --strictPort`,
      url: frontendURL,
      env: { HUMSAFAR_API_TARGET: "http://127.0.0.1:8765" },
      timeout: 60000,
      reuseExistingServer: false,
    },
  ],
});
