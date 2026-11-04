import { expect, test } from "@playwright/test";

const QUESTION = "傷害醫療保險金怎麼申請？";

// 真的後端：登入 → 選方案 → 進入問答頁 → 送出問題 → 看到回答與出處。
// 回答是白話說明或退回只顯示原文都算數（測試環境的 LLM 供應商不固定），一定要有出處。
test("選方案後可在問答頁送出問題，看到回答與出處", async ({ page, request }) => {
  const config = await (await request.get("/api/v1/auth/config")).json();
  test.skip(!config.dev_login, "後端沒有設 DEV_LOGIN_ENABLED=true");
  test.skip(!(await request.get("/api/v1/plans")).ok(), "條款庫沒有載入，先 make seed");

  const logs: string[] = [];
  page.on("console", (m) => logs.push(m.text()));

  await page.goto("/login?next=%2Fplans");
  await page.getByLabel("Email").fill("e2e-chat@example.com");
  await page.getByRole("button", { name: "測試登入" }).click();
  await page.getByTestId("plan-taian").getByRole("button", { name: "選這個方案" }).click();

  await expect(page).toHaveURL(/\/chat\/[0-9a-f-]{36}$/);
  await page.getByLabel("提問").fill(QUESTION);
  await page.getByRole("button", { name: "送出" }).click();

  await expect(page.getByTestId("message-assistant")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("message-user")).toHaveText(QUESTION);
  await expect(page.getByTestId("citation").first()).toContainText("第");
  await expect(page.getByTestId("citation").first()).toContainText("頁");

  // 重新整理後歷史還在
  await page.reload();
  await expect(page.getByTestId("message-assistant")).toBeVisible();

  expect(logs.join("\n")).not.toContain(QUESTION);
});

test("別人的或不存在的對話網址顯示找不到", async ({ page, request }) => {
  const config = await (await request.get("/api/v1/auth/config")).json();
  test.skip(!config.dev_login, "後端沒有設 DEV_LOGIN_ENABLED=true");

  await page.goto("/login?next=%2Faccount");
  await page.getByLabel("Email").fill("e2e-chat2@example.com");
  await page.getByRole("button", { name: "測試登入" }).click();
  await expect(page).toHaveURL(/\/account$/);

  await page.goto("/chat/00000000-0000-0000-0000-000000000000");
  await expect(page.getByRole("heading", { name: "找不到對話" })).toBeVisible();
  await expect(page.getByLabel("提問")).toHaveCount(0);
});
