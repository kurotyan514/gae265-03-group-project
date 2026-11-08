import { type APIRequestContext, expect, type Page, test } from "@playwright/test";
import { ADMIN_EMAIL, skipUnlessAdmin } from "./helpers";

// 開發工具頁：前端 → /api proxy → 後端（非 production 才有 GET /rules）→ 資料庫。
test("條文瀏覽列出資料庫裡的條文，點開可以看原文", async ({ page }) => {
  await page.goto("/dev/rules");
  await expect(page.getByTestId("total")).toContainText(/共 \d+ 筆/);
  const rows = page.locator("tbody tr");
  if ((await rows.count()) > 0) {
    await rows.first().click();
    await expect(page.locator("tbody pre").first()).not.toBeEmpty();
  }
});

test("條文瀏覽可以依險種篩選", async ({ page }) => {
  await page.goto("/dev/rules");
  const filter = page.getByTestId("insurance-filter");
  await expect(filter.locator("option")).not.toHaveCount(1); // 除了「全部」還有險種
  await filter.selectOption({ index: 1 });
  await expect(page.getByTestId("total")).toContainText(/共 \d+ 筆/);
});

test("API 測試台用範例送出報價，看到 200 與方案", async ({ page }) => {
  await page.goto("/dev");
  await expect(page).toHaveURL(/\/dev\/console$/);
  await page.getByTestId("operation").selectOption("quote_plans");
  await page.getByTestId("example").selectOption({ index: 1 }); // 第一個範例
  await page.getByRole("button", { name: "送出" }).click();
  await expect(page.getByTestId("status")).toHaveText("200");
  await expect(page.getByTestId("response")).toContainText('"plans"');
});

test("API 測試台送出無效內容時看到 422", async ({ page }) => {
  await page.goto("/dev/console");
  await page.getByTestId("operation").selectOption("quote_plans");
  await page.getByTestId("body").fill('{"days": 0, "travelers": []}');
  await page.getByRole("button", { name: "送出" }).click();
  await expect(page.getByTestId("status")).toHaveText("422");
});

/** 條款上傳的 API 要登入（ADR-0023）：用測試登入，登入後回到條款上傳頁。後端沒開測試登入時略過。 */
async function loginToIngest(page: Page, request: APIRequestContext) {
  const config = await (await request.get("/api/v1/auth/config")).json();
  test.skip(!config.dev_login, "後端沒有設 DEV_LOGIN_ENABLED=true");
  await page.goto("/login?next=%2Fdev%2Fingest");
  await page.getByLabel("Email").fill(ADMIN_EMAIL);
  await page.getByRole("button", { name: "測試登入" }).click();
  await expect(page).toHaveURL(/\/dev\/ingest$/);
  await skipUnlessAdmin(page);
}

test("條款上傳：上傳 PDF 後即時看到每個步驟完成", async ({ page, request }) => {
  // 條款處理走真的 LLM，單測預設 30 秒會比內部 60 秒的 expect 先逾時
  test.setTimeout(120_000);
  await loginToIngest(page, request);
  await page.getByTestId("file").setInputFiles("../backend/data/clauses/taian.pdf");
  await page.getByPlaceholder("FUBON07").fill("FUBON07");
  await page.getByPlaceholder("旅遊不便險").fill("旅遊不便險");
  await page.getByRole("button", { name: "上傳並處理" }).click();
  // 用台安的 PDF 配富邦的代碼，內容驗證會判定不符而停在「待人工確認」（#91 之後）；這裡只看步驟有跑
  await expect(page.getByTestId("job-status")).toHaveText(/完成|不是條款|失敗|待人工確認/, {
    timeout: 60_000,
  });
  await expect(page.getByTestId("step-extract")).toHaveAttribute("data-status", "ok");
  await expect(page.getByTestId("step-classify")).not.toHaveAttribute("data-status", "pending");
});

test("條款上傳：非 PDF 檔被後端拒絕並顯示原因", async ({ page, request }) => {
  await loginToIngest(page, request);
  await page.getByTestId("file").setInputFiles({
    name: "a.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("not a pdf"),
  });
  await page.getByPlaceholder("FUBON07").fill("FUBON07");
  await page.getByPlaceholder("旅遊不便險").fill("旅遊不便險");
  await page.getByRole("button", { name: "上傳並處理" }).click();
  await expect(page.getByTestId("upload-error")).toContainText("PDF");
});
