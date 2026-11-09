import { expect, type Page, test } from "@playwright/test";

/**
 * 用測試登入（任何 email 都能登入，需要後端開 DEV_LOGIN_ENABLED）。
 * 登入後輪詢 `/auth/me` 直到回 200 才回來：只等網址變成首頁，並行時登入狀態偶爾還沒生效，
 * 接著用 `page.request` 打 API 就會 401「未登入」。
 */
export async function login(page: Page, email: string) {
  await page.goto("/login?next=%2F");
  await page.getByLabel("Email").fill(email);
  await page.getByRole("button", { name: "測試登入" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect
    .poll(async () => (await page.request.get("/api/v1/auth/me")).status(), { timeout: 10_000 })
    .toBe(200);
}

/** 後台的測試用管理者：後端的 `ADMIN_EMAILS` 要包含它（.env.example 已有）。 */
export const ADMIN_EMAIL = "e2e-admin@example.com";

/** 已用測試登入之後呼叫：目前登入的人不是管理者就略過（通常是本機 .env 的 ADMIN_EMAILS 沒有 ADMIN_EMAIL）。 */
export async function skipUnlessAdmin(page: Page) {
  const me = await (await page.request.get("/api/v1/auth/me")).json();
  test.skip(!me.is_admin, `後端的 ADMIN_EMAILS 要包含 ${ADMIN_EMAIL}（見 .env.example）`);
}
