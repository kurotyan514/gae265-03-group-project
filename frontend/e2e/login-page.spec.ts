import { expect, type Page, test } from "@playwright/test";

// 0-2 登入頁（對照設計稿）：登入設定用假的回應，不連 Google，也不需要後端開哪些登入方式。
async function openLogin(page: Page, config: { dev_login: boolean; google_login: boolean }) {
  await page.route("**/api/v1/auth/config", (route) => route.fulfill({ json: config }));
  await page.goto("/login?next=%2F");
}

test("Google 已設定、測試登入關閉（正式環境的樣子）：只有 Google 鈕，沒有任何測試登入", async ({
  page,
}) => {
  await openLogin(page, { dev_login: false, google_login: true });

  await expect(page.getByRole("heading", { level: 1 })).toHaveText("好險有你");
  await expect(page.getByText("出發前幫你選方案，出事時幫你處理理賠。")).toBeVisible();
  const google = page.getByTestId("google-login");
  await expect(google).toContainText("使用 Google 帳號登入");
  await expect(google).toHaveAttribute("href", /\/api\/v1\/auth\/google\/login\?next=%2F$/);
  await expect(page.getByLabel("Email")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "測試登入" })).toHaveCount(0);
  // 滿版兩欄：左邊插畫、右邊內容
  const art = await page.locator("main img").boundingBox();
  const logo = await page.getByRole("heading", { level: 1 }).boundingBox();
  const viewport = page.viewportSize();
  expect(art && logo && viewport).toBeTruthy();
  expect(art?.x).toBe(0);
  expect(art?.width).toBeCloseTo((viewport?.width ?? 0) / 2, -1);
  expect((logo?.x ?? 0) > (art?.width ?? 0)).toBeTruthy();
});

test("兩種登入都開（本機開發）：Google 鈕在上，測試登入縮成下面的小區塊", async ({ page }) => {
  await openLogin(page, { dev_login: true, google_login: true });

  const google = await page.getByTestId("google-login").boundingBox();
  const dev = await page.getByLabel("Email").boundingBox();
  expect(google && dev && dev.y > google.y + google.height).toBeTruthy();
  await expect(page.getByText("測試登入（僅開發環境）")).toBeVisible();
  await expect(page.getByRole("button", { name: "測試登入" })).toBeVisible();
});

test("只有測試登入（Google 還沒設定）：說明還缺哪些設定", async ({ page }) => {
  await openLogin(page, { dev_login: true, google_login: false });

  await expect(page.getByTestId("google-login")).toHaveCount(0);
  await expect(page.getByText("Google 登入還沒設定")).toContainText("TOKEN_ENCRYPTION_KEY");
  await expect(page.getByLabel("Email")).toBeVisible();
});

test("兩種都沒開：說明登入功能尚未開放", async ({ page }) => {
  await openLogin(page, { dev_login: false, google_login: false });
  await expect(page.getByText("登入功能尚未開放，請聯絡管理者。")).toBeVisible();
});

test("手機寬度（390px）：插畫在上、Google 鈕在標語下面、沒有橫向捲動", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openLogin(page, { dev_login: false, google_login: true });

  const art = await page.locator("main img").boundingBox();
  const logo = await page.getByRole("heading", { level: 1 }).boundingBox();
  const google = await page.getByTestId("google-login").boundingBox();
  expect(art && logo && google).toBeTruthy();
  expect((logo?.y ?? 0) > (art?.y ?? 0) + (art?.height ?? 0) - 1).toBeTruthy();
  expect((google?.y ?? 0) > (logo?.y ?? 0) + (logo?.height ?? 0)).toBeTruthy();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(overflow).toBe(false);
});
