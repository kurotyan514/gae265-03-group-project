import { expect, type Page, test } from "@playwright/test";

// 打包寄送測試台（/dev/package）：用 7 號真正的程式，從虛構的範例事件產生送件信。
// 不需要登入、不需要 make seed、不連 Google（Google 授權是模擬的）。

/** 按「好險有你小助理幫我送出」，依序在 Drive、Gmail 的說明視窗按同意（模擬授權）。 */
async function assistWithGoogle(page: Page) {
  await page.getByRole("button", { name: "好險有你小助理幫我送出" }).click();
  const consent = page.getByTestId("google-consent");
  await expect(consent).toContainText("Google Drive");
  await page.getByTestId("google-consent-continue").click();
  await expect(consent).toContainText("Gmail");
  await page.getByTestId("google-consent-continue").click();
  await expect(consent).toHaveCount(0);
}

test("打包寄送測試台：資料都抓不到時，空格都標色，寄出前提醒列出十項", async ({ page }) => {
  await page.goto("/dev/package");
  await page.getByRole("button", { name: "資料都抓不到", exact: true }).click();
  await assistWithGoogle(page);

  // 信件裡每個「（請填寫＋項目）」都標色（內文十處，主旨另有保險期間）
  const body = page.getByTestId("letter-body");
  await expect(body).toContainText("（請填寫被保險人姓名）");
  await expect(body.getByTestId("blank")).toHaveCount(10);
  await expect(page.getByTestId("letter-subject").getByTestId("blank")).toHaveCount(1);

  // 寄出前：信裡還有空格，跳出提醒，列出要填的項目（重複的只列一次）
  await page.getByRole("button", { name: "寄出" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("還有 10 項要填寫");
  await expect(dialog.getByTestId("missing-item")).toHaveCount(10);
  await expect(dialog).toContainText("聯絡電話");
  await dialog.getByRole("button", { name: "我知道了" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("打包寄送測試台：資料齊全時只剩平台沒有的三項", async ({ page }) => {
  await page.goto("/dev/package");
  await page.getByRole("button", { name: "資料齊全", exact: true }).click();
  await assistWithGoogle(page);

  await expect(page.getByTestId("letter-subject")).toContainText("富邦國外旅平險-進階型");
  await expect(page.getByTestId("letter-body").getByTestId("blank")).toHaveCount(3);
  await expect(page.getByTestId("attachment")).toHaveCount(3);

  await page.getByRole("button", { name: "寄出" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("還有 3 項要填寫");
  await expect(dialog.getByTestId("missing-item")).toHaveText([
    "被保險人姓名",
    "保單號碼",
    "聯絡電話",
  ]);
});

test("打包寄送測試台：選了範例先問要不要幫忙寄，還沒看到信", async ({ page }) => {
  await page.goto("/dev/package");
  await page.getByRole("button", { name: "資料齊全", exact: true }).click();

  await expect(page.getByText("要由我們用你的 Gmail 幫你寄給保險公司嗎？")).toBeVisible();
  await expect(page.getByRole("button", { name: "我自己處理就好" })).toBeVisible();
  await expect(page.getByRole("button", { name: "好險有你小助理幫我送出" })).toBeVisible();
  await expect(page.getByTestId("letter-body")).toHaveCount(0);
});

test("打包寄送測試台：Drive 已授權時只問 Gmail", async ({ page }) => {
  await page.goto("/dev/package");
  await page.getByRole("checkbox", { name: "模擬：Google Drive 已授權" }).check();
  await page.getByRole("button", { name: "資料齊全", exact: true }).click();

  await page.getByRole("button", { name: "好險有你小助理幫我送出" }).click();
  const consent = page.getByTestId("google-consent");
  await expect(consent).toContainText("Gmail");
  await expect(consent).not.toContainText("Google Drive");
  await page.getByTestId("google-consent-continue").click();
  await expect(page.getByTestId("letter-body")).toBeVisible();
});

test("打包寄送測試台：兩個都已授權時直接看到信", async ({ page }) => {
  await page.goto("/dev/package");
  await page.getByRole("checkbox", { name: "模擬：Google Drive 已授權" }).check();
  await page.getByRole("checkbox", { name: "模擬：Gmail 已授權" }).check();
  await page.getByRole("button", { name: "資料齊全", exact: true }).click();

  await page.getByRole("button", { name: "好險有你小助理幫我送出" }).click();
  await expect(page.getByTestId("google-consent")).toHaveCount(0);
  await expect(page.getByTestId("letter-body")).toBeVisible();
});

test("打包寄送測試台：在授權說明按先不要，停在詢問畫面", async ({ page }) => {
  await page.goto("/dev/package");
  await page.getByRole("button", { name: "資料齊全", exact: true }).click();

  await page.getByRole("button", { name: "好險有你小助理幫我送出" }).click();
  await page.getByTestId("google-consent-cancel").click();
  await expect(page.getByTestId("google-consent")).toHaveCount(0);
  await expect(page.getByText("要由我們用你的 Gmail 幫你寄給保險公司嗎？")).toBeVisible();
  await expect(page.getByTestId("letter-body")).toHaveCount(0);
});

test("打包寄送測試台：我自己處理就好，不用授權，看到信可以複製", async ({ page }) => {
  await page.goto("/dev/package");
  await page.getByRole("button", { name: "資料齊全", exact: true }).click();

  await page.getByRole("button", { name: "我自己處理就好" }).click();
  await expect(page.getByTestId("google-consent")).toHaveCount(0);
  await expect(page.getByTestId("letter-body")).toBeVisible();
  await expect(page.getByRole("button", { name: "複製主旨" })).toBeVisible();
  await expect(page.getByRole("button", { name: "複製內文" })).toBeVisible();
  // 使用者自己寄，畫面上沒有「寄出」
  await expect(page.getByRole("button", { name: "寄出", exact: true })).toHaveCount(0);
});
