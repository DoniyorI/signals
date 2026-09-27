import { defineConfig, devices } from "@playwright/test";

const external = process.env.E2E_BASE_URL;

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  use: { baseURL: external ?? "http://127.0.0.1:5174" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  // Mock mode by default; set E2E_BASE_URL to run against a real stack.
  webServer: external
    ? undefined
    : {
        command: "npm run dev -- --port 5174",
        url: "http://127.0.0.1:5174",
        env: { VITE_MOCK: "1" },
        reuseExistingServer: !process.env.CI,
      },
});
