import { expect, test } from "@playwright/test";

// 用測試登入走完整條路線：前端 → 後端 session cookie → 資料庫的使用者。
// 後端沒開 DEV_LOGIN_ENABLED 時略過。
test("未登入進入我的帳號會被帶到登入頁，登入後回到原頁，登出後又被擋", async ({
  page,
  request,
}) => {
  const config = await (await request.get("/api/v1/auth/config")).json();
  test.skip(!config.dev_login, "後端沒有設 DEV_LOGIN_ENABLED=true");

  await page.goto("/account");
  await expect(page).toHaveURL(/\/login\?.*next=%2Faccount/);

  await page.getByLabel("Email").fill("e2e@example.com");
  await page.getByRole("button", { name: "測試登入" }).click();

  await expect(page).toHaveURL(/\/account$/);
  await expect(page.getByTestId("account-email")).toHaveText("e2e@example.com");

  // 重新整理仍是登入狀態：登入狀態在後端的 cookie，不是前端記憶體
  await page.reload();
  await expect(page.getByTestId("account-email")).toHaveText("e2e@example.com");

  await page.getByRole("button", { name: "登出" }).click();
  await expect(page).toHaveURL(/\/login/);

  await page.goto("/account");
  await expect(page).toHaveURL(/\/login\?.*next=%2Faccount/);
});
