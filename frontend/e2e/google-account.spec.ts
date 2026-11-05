import { expect, type Page, test } from "@playwright/test";

// 帳號頁的 Google 授權區塊（ADR-0020）。
// e2e 不能真的用 Google 登入，所以攔下瀏覽器對後端的請求、回傳假的登入者與授權狀態，
// 只驗證前端畫面的行為；後端的行為由 backend/tests/google 驗證。

type Grant = { status: "none" | "active" | "revoked" | "invalid"; drive: boolean; gmail: boolean };

async function asGoogleUser(page: Page, grant: Grant): Promise<{ revoked: () => boolean }> {
  let current = grant;
  let revoked = false;
  await page.route("**/api/v1/auth/config", (route) =>
    route.fulfill({ json: { dev_login: true, google_login: true } }),
  );
  await page.route("**/api/v1/auth/me", (route) =>
    route.fulfill({
      json: {
        id: "00000000-0000-0000-0000-0000000000bb",
        email: "carol@example.com",
        name: "Carol",
        login_provider: "google",
      },
    }),
  );
  await page.route("**/api/v1/auth/google/grant", (route) => route.fulfill({ json: current }));
  await page.route("**/api/v1/auth/google/revoke", (route) => {
    revoked = true;
    current = { status: "revoked", drive: false, gmail: false };
    return route.fulfill({ status: 204 });
  });
  return { revoked: () => revoked };
}

test("測試登入的帳號看不到 Google 授權區塊", async ({ page, request }) => {
  const config = await (await request.get("/api/v1/auth/config")).json();
  test.skip(!config.dev_login, "後端沒有設 DEV_LOGIN_ENABLED=true");

  await page.goto("/login?next=%2Faccount");
  await page.getByLabel("Email").fill("e2e-google-panel@example.com");
  await page.getByRole("button", { name: "測試登入" }).click();
  await expect(page.getByTestId("account-email")).toHaveText("e2e-google-panel@example.com");
  await expect(page.getByTestId("google-grant")).toHaveCount(0);
});

test("沒授權過：兩項都顯示尚未授權，按授權先看到用途說明", async ({ page }) => {
  await asGoogleUser(page, { status: "none", drive: false, gmail: false });
  await page.goto("/account");

  await expect(page.getByTestId("grant-drive")).toHaveText("尚未授權");
  await expect(page.getByTestId("grant-gmail")).toHaveText("尚未授權");
  await expect(page.getByTestId("google-revoke")).toHaveCount(0); // 沒授權就沒有取消

  await page.getByTestId("grant-drive-authorize").click();
  const dialog = page.getByTestId("google-consent");
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("Google Drive");
  // 同意後整頁前往後端的授權路由，授權完回到帳號頁
  await expect(page.getByTestId("google-consent-continue")).toHaveAttribute(
    "href",
    "/api/v1/auth/google/authorize?purpose=drive&next=%2Faccount",
  );

  // 先不要：關掉，什麼都不發生
  await page.getByTestId("google-consent-cancel").click();
  await expect(dialog).toHaveCount(0);
  await expect(page).toHaveURL(/\/account$/);
});

test("Gmail 的用途說明講的是寄信", async ({ page }) => {
  await asGoogleUser(page, { status: "active", drive: true, gmail: false });
  await page.goto("/account");

  await expect(page.getByTestId("grant-drive")).toHaveText("可以使用");
  await expect(page.getByTestId("grant-drive-authorize")).toHaveCount(0);
  await page.getByTestId("grant-gmail-authorize").click();
  await expect(page.getByTestId("google-consent")).toContainText("Gmail");
  await expect(page.getByTestId("google-consent-continue")).toHaveAttribute(
    "href",
    "/api/v1/auth/google/authorize?purpose=gmail&next=%2Faccount",
  );
});

test("授權失效時提示重新授權", async ({ page }) => {
  await asGoogleUser(page, { status: "invalid", drive: false, gmail: false });
  await page.goto("/account");
  await expect(page.getByTestId("grant-drive")).toHaveText("已失效，需要重新授權");
  await expect(page.getByTestId("grant-drive-authorize")).toBeVisible();
});

test("取消 Google 授權要先在頁面上確認", async ({ page }) => {
  const api = await asGoogleUser(page, { status: "active", drive: true, gmail: true });
  await page.goto("/account");
  await expect(page.getByTestId("grant-gmail")).toHaveText("可以使用");

  await page.getByTestId("google-revoke").click();
  await expect(page.getByTestId("google-revoke-confirm")).toContainText("不會被刪除");
  expect(api.revoked()).toBe(false); // 只按第一下不會取消

  await page.getByTestId("google-revoke-yes").click();
  await expect(page.getByTestId("grant-drive")).toHaveText("已取消");
  await expect(page.getByTestId("grant-gmail")).toHaveText("已取消");
  expect(api.revoked()).toBe(true);
});

test("從 Google 授權回來時顯示結果，並從網址拿掉", async ({ page }) => {
  await asGoogleUser(page, { status: "active", drive: true, gmail: false });
  await page.goto("/account?google_auth=granted");
  await expect(page.getByTestId("google-auth-result")).toHaveText("已完成 Google 授權。");
  await expect(page).not.toHaveURL(/google_auth/);

  await page.goto("/account?google_auth=account_mismatch");
  await expect(page.getByTestId("google-auth-result")).toContainText("帳號不同");
});
