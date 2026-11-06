import { expect, test } from "@playwright/test";

const SLOW = 30_000;

// 出事了的正式流程（/incident/*）：手選方案與保額 → 說明狀況 → 待辦 → 上傳文件 → 送件。
// 用後端目前設定的 agent 實作（預設是假實作）。需要測試登入與已載入的條款庫、方案資料（make seed）。
test("出事了：手選保單後走完 說明、待辦、上傳、送件", async ({ page, request }) => {
  const config = await (await request.get("/api/v1/auth/config")).json();
  test.skip(!config.dev_login, "後端沒有設 DEV_LOGIN_ENABLED=true");
  test.skip(!(await request.get("/api/v1/plans")).ok(), "條款庫沒有載入，先 make seed");

  await page.goto("/login?next=%2F");
  await page.getByLabel("Email").fill("e2e-incident-flow@example.com");
  await page.getByRole("button", { name: "測試登入" }).click();
  await expect(page).toHaveURL(/\/$/);

  // 入口：首頁的卡片進到 /incident/new
  await page.getByRole("link", { name: /出事了：幫我處理理賠/ }).click();
  await expect(page).toHaveURL(/\/incident\/new$/);

  // 1. 沒有保單檔：自己選方案與保額
  await page.getByTestId("mode-manual").click();
  await page.getByTestId("manual-plan").selectOption("fubon_advanced");
  const sums = page.getByTestId("manual-sum-insured");
  await expect(sums.locator("option")).not.toHaveCount(1);
  await sums.selectOption({ index: 1 });
  await page.getByTestId("create-manual-policy").click();
  await expect(page.getByTestId("policy")).toContainText("富邦國外旅平險-進階型");

  // 2. 說明發生什麼事，助理先問第一個問題
  await page.getByLabel("簡單說明").fill("班機延誤了六小時");
  await page.getByTestId("start").click();
  await expect(page).toHaveURL(/\/incident\/[0-9a-f-]+$/, { timeout: SLOW });
  await expect(page.getByTestId("messages").locator("li")).toHaveCount(2, { timeout: SLOW });

  // 對話：問完才判斷出類型，補上待辦
  const reply = () =>
    page.waitForResponse((r) => r.url().endsWith("/messages") && r.request().method() === "POST", {
      timeout: SLOW,
    });
  let replied = reply();
  await page.getByTestId("message").fill("班機延誤了六小時");
  await page.getByTestId("send").click();
  await replied;
  await expect(page.getByTestId("messages").locator("li")).toHaveCount(4, { timeout: SLOW });
  replied = reply();
  await page.getByTestId("message").fill("昨天在東京成田機場");
  await page.getByTestId("send").click();
  await replied;
  await expect(page.getByTestId("todos").getByRole("checkbox").first()).toBeVisible({
    timeout: SLOW,
  });

  // 3. 上傳文件：假 6 號依檔名辨識通過並勾選待辦
  await page.getByRole("link", { name: /2\. 上傳文件/ }).click();
  await page.getByTestId("doc-file").setInputFiles({
    name: "延誤證明.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("%PDF-1.4"),
  });
  await page.getByTestId("upload").click();
  await expect(page.getByTestId("notice")).toContainText("辨識通過", { timeout: SLOW });

  // 4. 送件：待辦沒完成前不能送
  await page.getByRole("link", { name: /3\. 送件/ }).click();
  await expect(page.getByTestId("ready")).toContainText("還有");
  await expect(page.getByTestId("submit")).toBeDisabled();

  // 回到待辦把剩下的自己勾完，就能預覽與送件
  await page.getByRole("link", { name: /1\. 說明與待辦/ }).click();
  const boxes = page.getByTestId("todos").getByRole("checkbox");
  await expect(boxes.first()).toBeVisible();
  for (const box of await boxes.all()) {
    if (!(await box.isChecked()) && (await box.isEnabled())) {
      const patched = page.waitForResponse((r) => r.request().method() === "PATCH");
      // 勾選要等後端回應才會變，所以用 click 再等回應，不用 check()
      await box.click();
      await patched;
    }
  }
  await page.getByRole("link", { name: /3\. 送件/ }).click();
  await expect(page.getByTestId("ready")).toContainText("可以送件");
  await page.getByTestId("package").click();
  await expect(page.getByTestId("package-view")).toBeVisible({ timeout: SLOW });
  await page.getByTestId("recipient").fill("agent@example.com");
  await page.getByTestId("submit").click();
  await expect(page.getByTestId("submission")).toBeVisible({ timeout: SLOW });
});
