import { expect, test } from "@playwright/test";

// 測試登入 → 選保單頁列出方案 → 選定後建立對話並進入問答頁。條款庫沒載入（make seed）時方案清單會失敗，略過。
test("登入後可在選保單頁選方案並建立對話", async ({ page, request }) => {
  const config = await (await request.get("/api/v1/auth/config")).json();
  test.skip(!config.dev_login, "後端沒有設 DEV_LOGIN_ENABLED=true");
  test.skip(!(await request.get("/api/v1/plans")).ok(), "條款庫沒有載入，先 make seed");

  await page.goto("/login?next=%2Fplans");
  await page.getByLabel("Email").fill("e2e-plans@example.com");
  await page.getByRole("button", { name: "測試登入" }).click();

  await expect(page).toHaveURL(/\/plans$/);
  const plan = page.getByTestId("plan-taian");
  await expect(plan).toContainText("TAIAN01");
  await expect(plan).toContainText("TAIAN03");

  await plan.getByRole("button", { name: "選這個方案" }).click();
  await expect(page).toHaveURL(/\/chat\/[0-9a-f-]{36}$/);
  await expect(page.getByLabel("提問")).toBeVisible();
});
