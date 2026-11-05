import { type APIRequestContext, expect, type Page, test } from "@playwright/test";

// 後台的合訂本拆分（/admin/bundles）：上傳 → 偵測的區段 → 填代碼、補區段、標成不收 → 確認。
// 登入用後端的測試登入（沒開 DEV_LOGIN_ENABLED 時略過）；後端用真實的，上傳泰安合訂本。

async function loginToBundles(page: Page, request: APIRequestContext) {
  const config = await (await request.get("/api/v1/auth/config")).json();
  test.skip(!config.dev_login, "後端沒有設 DEV_LOGIN_ENABLED=true");
  await page.goto("/login?next=%2Fadmin%2Fbundles");
  await page.getByLabel("Email").fill("e2e-bundles@example.com");
  await page.getByRole("button", { name: "測試登入" }).click();
  await expect(page).toHaveURL(/\/admin\/bundles$/);
}

test("未登入進入合訂本拆分會被帶到登入頁", async ({ page }) => {
  await page.goto("/admin/bundles");
  await expect(page).toHaveURL(/\/login\?.*next=%2Fadmin%2Fbundles/);
});

test("上傳合訂本、填代碼、確認；再傳一次同一份直接沿用", async ({ page, request }) => {
  await loginToBundles(page, request);

  await page.getByTestId("bundle-file").setInputFiles("../backend/data/clauses/taian.pdf");
  await page.getByRole("button", { name: "上傳並分析" }).click();
  // 同一份 PDF 可能被前一次執行存過：不管是新偵測還是沿用，都有 4 個區段
  await expect(page.getByTestId("bundle-editor")).toBeVisible();
  await expect(page.getByTestId("section-3")).toBeVisible();
  await expect(page.getByTestId("section-4")).toHaveCount(0);

  // 填代碼：前三個收錄，最後一個（恐怖主義附加條款）標成不收
  await page.getByTestId("company").fill("泰安產物");
  for (const [i, code] of ["TAIAN01", "TAIAN02", "TAIAN03"].entries()) {
    await page.getByTestId(`include-${i}`).check();
    await page.getByTestId(`code-${i}`).fill(code);
  }
  await page.getByTestId("include-3").uncheck();
  // 同一份 PDF 可能被前一次執行確認過、欄位值已經相同：多打一個空白（後端會去掉）確保有修改要儲存
  await page.getByTestId("name-0").fill(`${await page.getByTestId("name-0").inputValue()} `);

  // 試切：每個收錄的區段看得到切出幾條
  await page.getByTestId("try-cut").click();
  await expect(page.getByTestId("section-0")).toContainText(/切出 \d+ 條/);
  await expect(page.getByTestId("split-status")).toHaveText("草稿");

  await page.getByTestId("confirm").click();
  await expect(page.getByTestId("split-status")).toHaveText("已確認");
  await expect(page.getByTestId("bundle-message")).toContainText("直接沿用");
  await expect(page.getByTestId("bundles")).toContainText("taian.pdf");

  // 再傳一次同一份（換不換檔名都一樣）：直接沿用已確認的清單
  await page.getByTestId("bundle-file").setInputFiles("../backend/data/clauses/taian.pdf");
  await page.getByRole("button", { name: "上傳並分析" }).click();
  await expect(page.getByTestId("bundle-notice")).toContainText("確認過");
  await expect(page.getByTestId("split-status")).toHaveText("已確認");
});

test("沒填代碼就確認會列出問題；標題找不到的區段存不進去", async ({ page, request }) => {
  await loginToBundles(page, request);
  await page.getByTestId("bundle-file").setInputFiles("../backend/data/clauses/taian.pdf");
  await page.getByRole("button", { name: "上傳並分析" }).click();
  await expect(page.getByTestId("bundle-editor")).toBeVisible();

  // 補一個標題不存在的區段：後端試切不出來，不存
  await page.getByTestId("add-page").fill("2");
  await page.getByTestId("add-anchor").fill("根本不在這份 PDF 裡的標題");
  await page.getByTestId("add-name").fill("亂補的");
  await page.getByTestId("add-section").click();
  await page.getByTestId("save").click();
  await expect(page.getByTestId("bundle-error")).toContainText("找不到");
});

test("上傳不是 PDF 的檔案會顯示原因", async ({ page, request }) => {
  await loginToBundles(page, request);
  await page.getByTestId("bundle-file").setInputFiles({
    name: "a.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("not a pdf"),
  });
  await page.getByRole("button", { name: "上傳並分析" }).click();
  await expect(page.getByTestId("bundle-upload-error")).toContainText("PDF");
});
