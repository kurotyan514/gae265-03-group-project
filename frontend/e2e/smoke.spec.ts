import { expect, test } from "@playwright/test";

// 冒煙測試：前端 → 產生的 client → /api proxy → 後端 → 資料庫整條路線可用。
// 完全比對 "ok"：MSW 假資料回的是 "ok (mock)"，後端停掉時畫面只有錯誤訊息，兩者都會失敗。
test("首頁顯示後端回傳的健康狀態", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("health-status")).toHaveText("ok");
  await expect(page.getByTestId("health-db")).toHaveText("ok");
  await expect(page.getByTestId("health-pgvector")).toHaveText("ok");
});
