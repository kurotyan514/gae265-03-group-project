import { expect, test } from "@playwright/test";
import { ADMIN_EMAIL, skipUnlessAdmin } from "./helpers";

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
  await page.getByLabel("Email").fill(ADMIN_EMAIL);
  await page.getByRole("button", { name: "測試登入" }).click();
  await expect(page).toHaveURL(/\/account$/);
  await skipUnlessAdmin(page);

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

const JOBS = [
  {
    id: "00000000-0000-4000-8000-000000000001",
    filename: "chubb.pdf｜安達個人旅行綜合",
    insurance_code: "CHUBB06",
    insurance_name: "安達個人旅行綜合",
    status: "needs_review",
    summary: { pending: 3 },
    created_at: "2026-11-08T10:00:00Z",
  },
  {
    id: "00000000-0000-4000-8000-000000000002",
    filename: "fubon.pdf｜安心遊",
    insurance_code: "FUBON05",
    insurance_name: "安心遊",
    status: "needs_review",
    summary: { pending: 4 },
    created_at: "2026-11-08T10:01:00Z",
  },
  {
    id: "00000000-0000-4000-8000-000000000003",
    filename: "huanan.pdf｜恐怖主義",
    insurance_code: "HUANAN19",
    insurance_name: "恐怖主義",
    status: "failed",
    summary: null,
    created_at: "2026-11-08T10:02:00Z",
  },
  {
    id: "00000000-0000-4000-8000-000000000004",
    filename: "taian.pdf｜旅行平安",
    insurance_code: "TAIAN01",
    insurance_name: "旅行平安",
    status: "done",
    summary: { imported: 23 },
    created_at: "2026-11-08T10:03:00Z",
  },
];

test("上傳紀錄可以依狀態篩選，也能用檔名或險種代碼搜尋，待人工確認的顯示待處理條數", async ({
  page,
  request,
}) => {
  const config = await (await request.get("/api/v1/auth/config")).json();
  test.skip(!config.dev_login, "後端沒有設 DEV_LOGIN_ENABLED=true");
  await page.route("**/api/v1/ingest/jobs", (route) =>
    route.request().method() === "GET" ? route.fulfill({ json: JOBS }) : route.fallback(),
  );

  await page.goto("/login?next=%2Fadmin%2Fingest");
  await page.getByLabel("Email").fill(ADMIN_EMAIL);
  await page.getByRole("button", { name: "測試登入" }).click();
  await expect(page).toHaveURL(/\/admin\/ingest$/);
  await skipUnlessAdmin(page);

  const jobs = page.getByTestId("jobs");
  await expect(jobs.locator("li")).toHaveCount(4);
  await expect(page.getByTestId("filter-all")).toContainText("全部（4）");
  await expect(page.getByTestId("filter-needs_review")).toContainText("待人工確認（2）");
  await expect(page.getByTestId("filter-failed")).toContainText("失敗（1）");
  await expect(page.getByTestId("filter-running")).toHaveCount(0); // 沒有處理中的就不佔位置

  // 待人工確認：只剩 2 筆，並顯示待處理條數
  await page.getByTestId("filter-needs_review").click();
  await expect(page.getByTestId("filter-needs_review")).toHaveAttribute("aria-pressed", "true");
  await expect(jobs.locator("li")).toHaveCount(2);
  await expect(jobs).toContainText("3 條待處理");
  await expect(jobs).toContainText("4 條待處理");
  await expect(jobs).not.toContainText("TAIAN01");

  // 搭配搜尋：待人工確認裡找 FUBON
  await page.getByTestId("job-search").fill("fubon");
  await expect(jobs.locator("li")).toHaveCount(1);
  await expect(jobs).toContainText("FUBON05");

  // 搜不到時說明沒有符合的，而不是顯示「還沒有上傳紀錄」
  await page.getByTestId("job-search").fill("不存在的險種");
  await expect(page.getByTestId("jobs-empty")).toHaveText("沒有符合的紀錄");

  // 回到全部
  await page.getByTestId("job-search").fill("");
  await page.getByTestId("filter-all").click();
  await expect(jobs.locator("li")).toHaveCount(4);
});

test("不是管理者看不到後台入口，直接輸入網址只會看到沒有權限", async ({ page, request }) => {
  const config = await (await request.get("/api/v1/auth/config")).json();
  test.skip(!config.dev_login, "後端沒有設 DEV_LOGIN_ENABLED=true");

  await page.goto("/login?next=%2Faccount");
  await page.getByLabel("Email").fill("e2e-member-not-admin@example.com"); // 不在 ADMIN_EMAILS
  await page.getByRole("button", { name: "測試登入" }).click();
  await expect(page).toHaveURL(/\/account$/);
  await expect(page.getByTestId("admin-link")).toHaveCount(0);

  for (const path of ["/admin/ingest", "/admin/bundles", "/admin/rules"]) {
    await page.goto(path);
    await expect(page.getByTestId("admin-forbidden")).toContainText("沒有權限");
  }
  // 後端也擋：不是只有畫面藏起來
  expect((await page.request.get("/api/v1/ingest/jobs")).status()).toBe(403);
  expect((await page.request.get("/api/v1/admin/rules")).status()).toBe(403);
});
