import { expect, test } from "@playwright/test";

// 後台的條款上傳頁（/admin/ingest）：要登入；顯示險種狀態（待處理條文、檢索自檢）。
// 登入用後端的測試登入（沒開 DEV_LOGIN_ENABLED 時略過）；險種清單攔截成固定資料。
const INSURANCES = [
  { code: "FUBON01", name: "旅行平安", rule_count: 30, pending_count: 0, retrieval_check: null },
  {
    code: "CHUBB05",
    name: "安達個人旅行綜合",
    rule_count: 38,
    pending_count: 3,
    retrieval_check: {
      top_n: 3,
      threshold: 0.95,
      checked: 38,
      passed: 35,
      rate: 0.9211,
      abnormal: true,
      failed: [20, 29, 34],
    },
  },
  {
    code: "TAIAN01",
    name: "台安",
    rule_count: 23,
    pending_count: 0,
    retrieval_check: {
      top_n: 3,
      threshold: 0.95,
      checked: 23,
      passed: 23,
      rate: 1,
      abnormal: false,
      failed: [],
    },
  },
];

test("未登入進入後台會被帶到登入頁", async ({ page }) => {
  await page.goto("/admin/ingest");
  await expect(page).toHaveURL(/\/login\?.*next=%2Fadmin%2Fingest/);
});

test("登入後 header 有後台入口，後台頁顯示險種的待處理條文與檢索自檢", async ({
  page,
  request,
}) => {
  const config = await (await request.get("/api/v1/auth/config")).json();
  test.skip(!config.dev_login, "後端沒有設 DEV_LOGIN_ENABLED=true");
  await page.route("**/api/v1/insurances", (route) => route.fulfill({ json: INSURANCES }));

  await page.goto("/login?next=%2Faccount");
  await page.getByLabel("Email").fill("e2e-admin@example.com");
  await page.getByRole("button", { name: "測試登入" }).click();
  await expect(page).toHaveURL(/\/account$/);

  await page.getByTestId("admin-link").click();
  await expect(page).toHaveURL(/\/admin\/ingest$/);
  await expect(page.getByTestId("upload-form")).toBeVisible();

  const panel = page.getByTestId("insurance-status");
  await expect(panel).toContainText("共 3 個險種");
  await expect(panel).toContainText("待處理條文 3 條");
  await expect(panel).toContainText("檢索品質異常 1 個");
  await panel.locator("summary").click();
  // 有問題的排在最前面
  await expect(panel.locator("tbody tr").first()).toContainText("CHUBB05");
  await expect(page.getByTestId("insurance-CHUBB05")).toContainText("3 條");
  await expect(page.getByTestId("insurance-CHUBB05")).toContainText("檢索品質異常");
  await expect(page.getByTestId("insurance-CHUBB05")).toContainText("找不到：20、29、34");
  await expect(page.getByTestId("insurance-TAIAN01")).toContainText("23/23");
  await expect(page.getByTestId("insurance-FUBON01")).toContainText("未做");
});
