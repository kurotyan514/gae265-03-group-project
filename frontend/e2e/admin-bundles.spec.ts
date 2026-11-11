import { type APIRequestContext, expect, type Page, test } from "@playwright/test";
import { ADMIN_EMAIL, skipUnlessAdmin } from "./helpers";

// 後台的合訂本拆分（/admin/bundles）：上傳 → 偵測的區段 → 填代碼、補區段、標成不收 → 確認。
// 登入用後端的測試登入（沒開 DEV_LOGIN_ENABLED 時略過）；後端用真實的，上傳泰安合訂本。

async function loginToBundles(page: Page, request: APIRequestContext) {
  const config = await (await request.get("/api/v1/auth/config")).json();
  test.skip(!config.dev_login, "後端沒有設 DEV_LOGIN_ENABLED=true");
  await page.goto("/login?next=%2Fadmin%2Fbundles");
  await page.getByLabel("Email").fill(ADMIN_EMAIL);
  await page.getByRole("button", { name: "測試登入" }).click();
  await expect(page).toHaveURL(/\/admin\/bundles$/);
  await skipUnlessAdmin(page);
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

test("不收的區段（skip_ 代碼）勾成收錄時，自動帶入下一個可用的代碼", async ({ page, request }) => {
  await loginToBundles(page, request);
  await page.getByTestId("bundle-file").setInputFiles("../backend/data/clauses/taian.pdf");
  await page.getByRole("button", { name: "上傳並分析" }).click();
  await expect(page.getByTestId("bundle-editor")).toBeVisible();

  // 不儲存，不影響已存的清單：前三個填 TAIAN01～03，第 4 個用設定檔那種 skip_ 代碼
  for (const [i, code] of ["TAIAN01", "TAIAN02", "TAIAN03"].entries()) {
    await page.getByTestId(`include-${i}`).check();
    await page.getByTestId(`code-${i}`).fill(code);
  }
  await page.getByTestId("include-3").check();
  await page.getByTestId("code-3").fill("skip_taian_terror");
  await page.getByTestId("include-3").uncheck();
  await page.getByTestId("include-3").check();
  // 下一個可用代碼 = 這份清單與資料庫已有的 TAIAN 代碼的最大號碼加一（資料庫可能已有 TAIAN04）
  const insurances = (await (await page.request.get("/api/v1/insurances")).json()) as {
    code: string;
  }[];
  const taken = insurances
    .map((i) => /^TAIAN(\d+)$/.exec(i.code)?.[1])
    .filter((n): n is string => n !== undefined)
    .map(Number);
  const next = String(Math.max(3, ...taken) + 1).padStart(2, "0");
  await expect(page.getByTestId("code-3")).toHaveValue(`TAIAN${next}`);

  // 不是 skip_ 開頭的代碼不會被改掉
  await page.getByTestId("code-3").fill("TAIAN09");
  await page.getByTestId("include-3").uncheck();
  await page.getByTestId("include-3").check();
  await expect(page.getByTestId("code-3")).toHaveValue("TAIAN09");
});

test("確認過的清單可以入庫：每個收錄的險種各建一個工作", async ({ page, request }) => {
  await loginToBundles(page, request);
  // 入庫會真的呼叫向量服務並寫入條款，e2e 不做：攔截成固定的回應，只驗證畫面與請求
  const calls: string[] = [];
  await page.route("**/api/v1/ingest/bundles/*/ingest", (route) => {
    calls.push(route.request().method());
    return route.fulfill({
      status: 202,
      json: [
        { job_id: "11111111-1111-4111-8111-111111111111", code: "TAIAN01", name: "旅行平安" },
        { job_id: "22222222-2222-4222-8222-222222222222", code: "TAIAN02", name: "傷害醫療" },
      ],
    });
  });

  await page.getByTestId("bundle-file").setInputFiles("../backend/data/clauses/taian.pdf");
  await page.getByRole("button", { name: "上傳並分析" }).click();
  await expect(page.getByTestId("bundle-editor")).toBeVisible();
  await page.getByTestId("company").fill("泰安產物");
  for (const [i, code] of ["TAIAN01", "TAIAN02", "TAIAN03"].entries()) {
    await page.getByTestId(`include-${i}`).check();
    await page.getByTestId(`code-${i}`).fill(code);
  }
  await page.getByTestId("include-3").uncheck();
  await page.getByTestId("name-0").fill(`${await page.getByTestId("name-0").inputValue()} `);

  // 還沒確認（草稿）不能入庫
  await expect(page.getByTestId("ingest")).toHaveCount(0);
  await page.getByTestId("confirm").click();
  await expect(page.getByTestId("split-status")).toHaveText("已確認");

  await page.getByTestId("ingest").click();
  await expect(page.getByTestId("ingest-jobs")).toContainText("已建立 2 個入庫工作");
  await expect(page.getByTestId("ingest-jobs")).toContainText("TAIAN02");
  expect(calls).toEqual(["POST"]);
});
