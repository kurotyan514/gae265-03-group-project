import { expect, test } from "@playwright/test";

// Google 登入（ADR-0020）：e2e 不連 Google，只確認登入頁導向正確、失敗原因顯示正確。
// 真的走一次 Google 是手動驗證（docs/agents/handoff/google-login.md 的驗證清單）。

test("登入頁的 Google 按鈕連到後端，並帶著登入後要回去的頁面", async ({ page, request }) => {
  const config = await (await request.get("/api/v1/auth/config")).json();
  test.skip(!config.google_login, "後端沒有設定 Google 登入（GOOGLE_CLIENT_ID 等）");

  await page.goto("/login?next=%2Faccount");
  await expect(page.getByTestId("google-login")).toHaveAttribute(
    "href",
    "/api/v1/auth/google/login?next=%2Faccount",
  );
});

test("登入頁不接受站外的 next，Google 登入後一律回站內", async ({ page, request }) => {
  const config = await (await request.get("/api/v1/auth/config")).json();
  test.skip(!config.google_login, "後端沒有設定 Google 登入（GOOGLE_CLIENT_ID 等）");

  await page.goto("/login?next=https%3A%2F%2Fevil.example.com");
  await expect(page.getByTestId("google-login")).toHaveAttribute(
    "href",
    "/api/v1/auth/google/login?next=%2Faccount",
  );
});

test("Google 登入失敗時顯示原因", async ({ page }) => {
  await page.goto("/login?error=email_unverified");
  await expect(page.getByTestId("login-error")).toContainText("尚未驗證");

  await page.goto("/login?error=cancelled");
  await expect(page.getByTestId("login-error")).toContainText("取消");

  // 不認得的代碼顯示一般訊息
  await page.goto("/login?error=something_else");
  await expect(page.getByTestId("login-error")).toContainText("登入失敗，請再試一次");
});
