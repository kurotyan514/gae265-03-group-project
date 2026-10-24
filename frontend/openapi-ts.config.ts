import { defineConfig } from "@hey-api/openapi-ts";

// openapi.json 由 `make client` 從後端的 `app.openapi()` 輸出，不必啟動 server 與資料庫
export default defineConfig({
  input: "openapi.json",
  output: "src/client",
  plugins: [
    // schema 沒有 servers，不關掉會拿 input 的路徑當 baseUrl；預設同源，`/api` 由 Vite proxy 或 Caddy 轉給後端
    { name: "@hey-api/client-fetch", baseUrl: false },
    "@hey-api/sdk",
    "@tanstack/react-query",
  ],
});
