import { HttpResponse, http } from "msw";
import { setupWorker } from "msw/browser";
import type { HealthStatus } from "../client/types.gen";

// 假資料模式（`VITE_MOCK=true`）攔下的 API；回應型別用產生的 client，後端 schema 改了這裡會型別錯誤
const handlers = [
  http.get("*/api/v1/health", () =>
    HttpResponse.json<HealthStatus>({ status: "ok", db: "ok (mock)", pgvector: "ok (mock)" }),
  ),
];

/** 只由 main.tsx 在 `VITE_MOCK` 判斷裡 dynamic import，正式 build 不會包含。 */
export async function startMockWorker(): Promise<void> {
  // 沒寫 handler 的請求照常送出（例如 Vite 自己的模組）
  await setupWorker(...handlers).start({ onUnhandledFrame: "bypass" });
}
