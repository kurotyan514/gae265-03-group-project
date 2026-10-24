import { defineConfig } from "@playwright/test";

// 不自動啟動伺服器：先 make up，再 make e2e。前端不在 localhost:5173 時用 E2E_BASE_URL 覆寫
export default defineConfig({
  testDir: "e2e",
  use: { baseURL: process.env.E2E_BASE_URL ?? "http://localhost:5173" },
});
