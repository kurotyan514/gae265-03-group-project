import { expect, test } from "@playwright/test";

const SLOW = 30_000;

// 事件流程測試台（/dev/incident）：用假實作走完 保單 → 事件 → 5 對話 → 6 上傳文件 → 7 送件。
// 需要測試登入與已載入的條款庫（make seed）；「建立範例保單」會一併載入範例事件類型。
test("事件流程測試台可以用假實作走完整條流程", async ({ page, request }) => {
  const config = await (await request.get("/api/v1/auth/config")).json();
  test.skip(!config.dev_login, "後端沒有設 DEV_LOGIN_ENABLED=true");
  test.skip(!(await request.get("/api/v1/plans")).ok(), "條款庫沒有載入，先 make seed");

  await page.goto("/login?next=%2Fdev%2Fincident");
  await page.getByLabel("Email").fill("e2e-incident@example.com");
  await page.getByRole("button", { name: "測試登入" }).click();
  await expect(page).toHaveURL(/\/dev\/incident$/);

  // 1. 保單與事件：沒有保單就建立範例保單，再開始事件，5 號 agent 先問第一個問題
  await page.getByTestId("sample-policy").click();
  await expect(page.getByTestId("policy")).not.toHaveValue("");
  await page.getByTestId("start").click();
  // 假 agent 會查條款，真的向量服務一次要好幾秒，所以等久一點
  await expect(page.getByTestId("incident")).toBeVisible({ timeout: SLOW });
  await expect(page.getByTestId("messages").locator("li")).toHaveCount(2);

  // 2. 對話：5 先追問，問完才判斷出班機延誤，補上該類型的待辦與出處
  await page.getByTestId("message").fill("班機延誤了六小時");
  await page.getByTestId("send").click();
  await expect(page.getByTestId("messages").locator("li")).toHaveCount(4, {
    timeout: SLOW,
  });
  await page.getByTestId("message").fill("昨天在東京成田機場");
  await page.getByTestId("send").click();
  await expect(
    page
      .getByTestId("incident")
      .getByText(/班機延誤 ·/)
      .first(),
  ).toBeVisible({
    timeout: SLOW,
  });
  await expect(page.getByTestId("citations")).toBeVisible();
  const todos = page.getByTestId("todos").getByRole("checkbox");
  await expect(todos.first()).toBeVisible();
  const todoCount = await todos.count();
  expect(todoCount).toBeGreaterThanOrEqual(2);

  // 4. 上傳文件：6 依檔名辨識通過，勾選第一個未完成的待辦並標示是系統判斷的
  await page.getByTestId("doc-file").setInputFiles({
    name: "延誤證明.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("%PDF-1.4"),
  });
  await page.getByTestId("upload").click();
  await expect(page.getByTestId("documents")).toContainText("辨識通過");
  await expect(page.getByTestId("todos")).toContainText("系統判斷完成");

  // 5. 還有待辦沒完成：送件被擋下，錯誤原樣顯示
  await page.getByTestId("submit").click();
  await expect(page.getByTestId("error")).toContainText("還有待辦沒完成");

  // 使用者勾完其他待辦後，可以預覽送件包並送件。
  // 不需上傳的手動勾；需上傳的會被後端擋下（409），改用上傳完成（依序處理，第一個未完成的就是這一項）
  for (let i = 0; i < todoCount; i++) {
    const box = todos.nth(i);
    if (await box.isChecked()) continue;
    await box.click(); // 狀態要等後端回應才更新，所以不用 check()
    try {
      await expect(box).toBeChecked({ timeout: 2000 });
    } catch {
      await page.getByTestId("doc-file").setInputFiles({
        name: "證明.pdf",
        mimeType: "application/pdf",
        buffer: Buffer.from("%PDF-1.4"),
      });
      await page.getByTestId("upload").click();
      await expect(box).toBeChecked();
    }
  }
  await expect(page.getByTestId("all-done")).toContainText("可以送件");
  await page.getByTestId("package").click();
  // 附件檔名是 6 號取的（事故類型_待辦名稱_序號），不是使用者上傳時的原檔名
  await expect(page.getByTestId("package-view")).toContainText("班機延誤_");
  await page.getByTestId("submit").click();
  await expect(page.getByTestId("submission")).toContainText("已寄出");
});

test("沒有登入時，事件流程測試台提示要先登入", async ({ page }) => {
  await page.goto("/dev/incident");
  await expect(page.getByText("要先登入才能試事件流程")).toBeVisible();
});
