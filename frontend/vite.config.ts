import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// 只從 shell 或 compose 的環境變數讀（Vite 不會把 .env 載進 config）；沒設時連本機的後端
const apiProxyTarget = process.env.API_PROXY_TARGET ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": apiProxyTarget,
    },
  },
});
