import { expect, type Page, test } from "@playwright/test";

/** 今天往後 offset 天的 YYYY-MM-DD（瀏覽器的本地日期）。 */
function day(offset: number): string {
  const d = new Date();
  d.setDate(d.getDate() + offset);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

async function login(page: Page, email: string) {
  await page.goto("/login?next=%2F");
  await page.getByLabel("Email").fill(email);
  await page.getByRole("button", { name: "測試登入" }).click();
  await expect(page).toHaveURL(/\/$/);
}

/** 每次用新的帳號，才不會被開發資料庫裡先前留下的比較紀錄影響。 */
const freshEmail = (name: string) => `e2e-home-${name}-${Date.now()}@example.com`;

/** 直接用 API 建一筆 1-1 填完的比較紀錄（登入的 cookie 在 page.request 裡）。 */
async function createComparison(page: Page, destination: string, departOffset: number) {
  const response = await page.request.post("/api/v1/comparisons", {
    data: {
      destination,
      depart_date: day(departOffset),
      return_date: day(departOffset + 5),
      age: 30,
    },
  });
  expect(response.ok()).toBeTruthy();
}

test.beforeEach(async ({ request }) => {
  const config = await (await request.get("/api/v1/auth/config")).json();
  test.skip(!config.dev_login, "後端沒有設 DEV_LOGIN_ENABLED=true");
});

// 首頁需要登入：未登入被帶到登入頁，登入後回首頁看到 header 與兩張入口卡，登出後又被擋。
test("未登入開首頁會到登入頁，登入後看到首頁，登出後要重新登入", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login\?.*next=%2F/);

  await page.getByLabel("Email").fill("e2e-home@example.com");
  await page.getByRole("button", { name: "測試登入" }).click();

  await expect(page).toHaveURL(/\/$/);
  const header = page.getByRole("banner");
  await expect(header.getByRole("link", { name: /好險有你/ })).toHaveAttribute("href", "/");
  // dev-login 沒給名稱時以 email 當名字
  await expect(header.getByTestId("header-user")).toHaveText("e2e-home@example.com");
  // 設計稿沒有「{名字}，你現在需要什麼？」：h1 只給畫面閱讀器讀
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("首頁");

  await expect(page.getByRole("link", { name: /出發前：幫我選方案/ })).toHaveAttribute(
    "href",
    "/compare/new",
  );
  await expect(page.getByRole("link", { name: /出事了：幫我處理理賠/ })).toHaveAttribute(
    "href",
    "/incident/new",
  );

  await header.getByRole("button", { name: "登出" }).click();
  await expect(page).toHaveURL(/\/login/);

  await page.goto("/");
  await expect(page).toHaveURL(/\/login\?.*next=%2F/);
});

test("沒有比較紀錄時，最近的比較顯示空狀態", async ({ page }) => {
  await login(page, freshEmail("empty"));

  const recent = page.getByRole("region", { name: "最近的比較" });
  await expect(recent.getByText("比較過的方案會自動存在這裡")).toBeVisible();
  await expect(recent.getByRole("link")).toHaveCount(0);
  await expect(recent.getByText("看全部")).toHaveCount(0);
});

test("推薦過的比較紀錄出現在首頁，點進去到 1-3，上一步到 1-2", async ({ page }) => {
  await login(page, freshEmail("recommended"));
  await page.goto("/compare/new");
  await page.getByLabel("目的地").selectOption("日本");
  await page.getByLabel("出發日").fill(day(7));
  await page.getByLabel("回程日").fill(day(12));
  await page.getByLabel("年齡").fill("30");
  await page.getByRole("button", { name: "下一步" }).click();
  await page.getByRole("button", { name: /^班機延誤/ }).click();
  await page.getByRole("button", { name: "下一步" }).click();
  await expect(page).toHaveURL(/\/result$/);
  await page.getByRole("link", { name: "完成" }).click();

  const recent = page.getByRole("region", { name: "最近的比較" });
  const row = recent.getByRole("link");
  await expect(row).toHaveCount(1);
  await expect(row.getByText(`日本 · ${day(7).replaceAll("-", "/")} · 6 天`)).toBeVisible();
  // 「推薦 {公司} {方案名} · {保額} 萬」
  await expect(row.getByText(/^推薦 .+ · [\d,]+ 萬$/)).toBeVisible();

  await row.click();
  await expect(page).toHaveURL(/\/compare\/[0-9a-f-]{36}\/result$/);
  await page.getByRole("link", { name: "上一步" }).click();
  await expect(page).toHaveURL(/\/compare\/[0-9a-f-]{36}\/concerns$/);
});

test("只填完 1-1 的比較紀錄顯示填寫中，點進去到 1-2", async ({ page }) => {
  await login(page, freshEmail("draft"));
  await createComparison(page, "韓國", 7);
  await page.goto("/");

  const row = page.getByRole("region", { name: "最近的比較" }).getByRole("link");
  await expect(row).toHaveCount(1);
  await expect(row.getByText(`韓國 · ${day(7).replaceAll("-", "/")} · 6 天`)).toBeVisible();
  await expect(row.getByText("填寫中")).toBeVisible();

  await row.click();
  await expect(page).toHaveURL(/\/compare\/[0-9a-f-]{36}\/concerns$/);
});

test("3 筆以下不顯示看全部", async ({ page }) => {
  await login(page, freshEmail("three"));
  for (const [i, destination] of ["日本", "韓國", "泰國"].entries()) {
    await createComparison(page, destination, 7 + i);
  }
  await page.goto("/");

  const recent = page.getByRole("region", { name: "最近的比較" });
  await expect(recent.getByRole("link")).toHaveCount(3);
  await expect(recent.getByText("看全部")).toHaveCount(0);
});

test("超過 3 筆時只列前 3 筆（最近操作的在最前面），看全部 → 全部比較頁 → 回首頁", async ({
  page,
}) => {
  await login(page, freshEmail("many"));
  for (const [i, destination] of ["日本", "韓國", "泰國", "新加坡"].entries()) {
    await createComparison(page, destination, 7 + i);
  }
  await page.goto("/");

  const recent = page.getByRole("region", { name: "最近的比較" });
  // 列是帶「天數」的連結；「看全部」不算
  const rows = recent.getByRole("link", { name: /天/ });
  await expect(rows).toHaveCount(3);
  await expect(rows.nth(0)).toContainText("新加坡");
  await expect(rows.nth(2)).toContainText("韓國");

  await recent.getByRole("link", { name: "看全部" }).click();
  await expect(page).toHaveURL(/\/compare$/);
  await expect(page.getByRole("heading", { level: 1, name: "全部比較" })).toBeVisible();
  await expect(page.getByText("共 4 筆，依最後操作時間由新到舊")).toBeVisible();
  await expect(page.getByRole("link", { name: "首頁", exact: true })).toHaveAttribute("href", "/");

  // 全部 4 筆，順序與首頁一致；點列的去向與首頁相同（只填 1-1 → 1-2）
  const all = page.getByRole("main").getByRole("link", { name: /天/ });
  await expect(all).toHaveCount(4);
  await expect(all.nth(0)).toContainText("新加坡");
  await expect(all.nth(3)).toContainText("日本");
  await all.nth(3).click();
  await expect(page).toHaveURL(/\/compare\/[0-9a-f-]{36}\/concerns$/);

  await page.goto("/compare");
  await page.getByRole("link", { name: "回首頁" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("region", { name: "最近的比較" })).toBeVisible();
});

test("沒有比較紀錄時，全部比較頁顯示目前沒有紀錄", async ({ page }) => {
  await login(page, freshEmail("all-empty"));
  await page.goto("/compare");

  await expect(page.getByText("共 0 筆，依最後操作時間由新到舊")).toBeVisible();
  await expect(page.getByText("目前沒有紀錄")).toBeVisible();
});
