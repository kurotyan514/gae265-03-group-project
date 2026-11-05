import { expect, test } from "@playwright/test";

// 首頁需要登入：未登入被帶到登入頁，登入後回首頁看到 header 與兩張卡片，登出後又被擋。
test("未登入開首頁會到登入頁，登入後看到首頁，登出後要重新登入", async ({ page, request }) => {
  const config = await (await request.get("/api/v1/auth/config")).json();
  test.skip(!config.dev_login, "後端沒有設 DEV_LOGIN_ENABLED=true");

  await page.goto("/");
  await expect(page).toHaveURL(/\/login\?.*next=%2F/);

  await page.getByLabel("Email").fill("e2e-home@example.com");
  await page.getByRole("button", { name: "測試登入" }).click();

  await expect(page).toHaveURL(/\/$/);
  const header = page.getByRole("banner");
  await expect(header.getByRole("link", { name: /好險有你/ })).toHaveAttribute("href", "/");
  // dev-login 沒給名稱時以 email 當名字
  await expect(header.getByTestId("header-user")).toHaveText("e2e-home@example.com");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "e2e-home@example.com，你現在需要什麼？",
  );

  await expect(page.getByRole("link", { name: /出發前：幫我選方案/ })).toHaveAttribute(
    "href",
    "/compare/new",
  );
  await expect(page.getByRole("button", { name: /出事了：幫我處理理賠/ })).toBeDisabled();

  await header.getByRole("button", { name: "登出" }).click();
  await expect(page).toHaveURL(/\/login/);

  await page.goto("/");
  await expect(page).toHaveURL(/\/login\?.*next=%2F/);
});
