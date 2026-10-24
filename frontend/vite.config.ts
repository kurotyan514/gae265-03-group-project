import tailwindcss from "@tailwindcss/vite";
import { tanstackRouter } from "@tanstack/router-plugin/vite";
import react from "@vitejs/plugin-react";
import { msw } from "msw/vite";
import { defineConfig } from "vite";

// 只從 shell 或 compose 的環境變數讀（Vite 不會把 .env 載進 config）；沒設時連本機的後端
const apiProxyTarget = process.env.API_PROXY_TARGET ?? "http://localhost:8000";

export default defineConfig({
  // tanstackRouter 要排在 react 之前：先產生路由樹，再交給 React 轉譯
  plugins: [
    tanstackRouter({ target: "react", autoCodeSplitting: true }),
    react(),
    tailwindcss(),
    // 假資料模式用：dev server 提供 MSW 的 service worker；build 不輸出 worker
    msw(),
  ],
  server: {
    host: true,
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": apiProxyTarget,
    },
  },
});
