import { expect, type Page, test } from "@playwright/test";
import { ADMIN_EMAIL, skipUnlessAdmin } from "./helpers";

// 後台的條文維護（/admin/rules）：要登入；展開條文後可以修改標題與內文，存檔時重新計算向量。
// 登入用後端的測試登入（沒開 DEV_LOGIN_ENABLED 時略過）；PATCH 攔截成固定回應，不改開發資料庫。
async function loginToRules(
  page: Page,
  request: Parameters<Parameters<typeof test>[2]>[0]["request"],
) {
  const config = await (await request.get("/api/v1/auth/config")).json();
  test.skip(!config.dev_login, "後端沒有設 DEV_LOGIN_ENABLED=true");
  await page.goto("/login?next=%2Fadmin%2Frules");
  await page.getByLabel("Email").fill(ADMIN_EMAIL);
  await page.getByRole("button", { name: "測試登入" }).click();
  await expect(page).toHaveURL(/\/admin\/rules$/);
  await skipUnlessAdmin(page);
  await expect(page.getByTestId("total")).toContainText(/共 \d+ 筆/); // 等清單載入再判斷
}

const UPDATED = {
  insurance_code: "X",
  insurance_name: "X",
  article_no: 1,
  chapter: "條文1",
  title: "新標題",
  content: "新內文",
  section: null,
  source_file: "x.pdf",
  page_start: 1,
  page_end: 1,
  embedding_models: ["m"],
  embedding_dimensions: 1024,
};

test("未登入進入條文維護會被帶到登入頁", async ({ page }) => {
  await page.goto("/admin/rules");
  await expect(page).toHaveURL(/\/login\?.*next=%2Fadmin%2Frules/);
});

test("後台條文可以編輯標題與內文，存檔時送出修改並顯示向量已重新計算", async ({
  page,
  request,
}) => {
  const sent: { url: string; body: unknown }[] = [];
  await page.route("**/api/v1/admin/rules/*/*", async (route) => {
    if (route.request().method() !== "PATCH") return route.fallback();
    sent.push({ url: route.request().url(), body: route.request().postDataJSON() });
    return route.fulfill({ json: UPDATED });
  });
  await loginToRules(page, request);
  const rows = page.locator("tbody tr");
  test.skip((await rows.count()) === 0, "資料庫沒有條文");
  await rows.first().click();
  await page.getByTestId("edit-rule").click();

  // 沒改任何東西不能存檔
  await expect(page.getByTestId("save-rule")).toBeDisabled();
  await page.getByTestId("edit-title").fill("新標題");
  await page.getByTestId("edit-content").fill("新內文");
  await page.getByTestId("edit-reason").fill("勘誤");
  await expect(page.getByTestId("save-rule")).toBeEnabled();
  await page.getByTestId("save-rule").click();

  await expect(page.getByTestId("edit-result")).toContainText("向量已重新計算（1024 維）");
  expect(sent).toHaveLength(1);
  expect(sent[0]?.url).toMatch(/\/admin\/rules\/[^/]+\/\d+$/);
  expect(sent[0]?.body).toEqual({ title: "新標題", content: "新內文", reason: "勘誤" });
});

test("條文編輯失敗時顯示後端的原因，內容留在表單裡", async ({ page, request }) => {
  await page.route("**/api/v1/admin/rules/*/*", async (route) => {
    if (route.request().method() !== "PATCH") return route.fallback();
    return route.fulfill({
      status: 502,
      json: { detail: "向量服務無法使用，標題與內文都沒有修改" },
    });
  });
  await loginToRules(page, request);
  const rows = page.locator("tbody tr");
  test.skip((await rows.count()) === 0, "資料庫沒有條文");
  await rows.first().click();
  await page.getByTestId("edit-rule").click();
  await page.getByTestId("edit-title").fill("會失敗的標題");
  await page.getByTestId("save-rule").click();

  await expect(page.getByTestId("edit-error")).toContainText("沒有修改");
  await expect(page.getByTestId("edit-title")).toHaveValue("會失敗的標題");
});

test("開發用的 /dev/rules 仍是唯讀，沒有編輯按鈕", async ({ page }) => {
  await page.goto("/dev/rules");
  await expect(page.getByTestId("total")).toContainText(/共 \d+ 筆/);
  const rows = page.locator("tbody tr");
  test.skip((await rows.count()) === 0, "資料庫沒有條文");
  await rows.first().click();
  await expect(page.locator("tbody pre").first()).not.toBeEmpty();
  await expect(page.getByTestId("edit-rule")).toHaveCount(0);
});
