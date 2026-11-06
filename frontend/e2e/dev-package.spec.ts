import { expect, test } from "@playwright/test";

// 打包寄送測試台（/dev/package）：用 7 號真正的程式，從虛構的範例事件產生送件信。
// 不需要登入、不需要 make seed、不連 Google。
test("打包寄送測試台：資料都抓不到時，空格都標色，寄出前提醒列出十項", async ({ page }) => {
  await page.goto("/dev/package");
  await page.getByRole("button", { name: "資料都抓不到", exact: true }).click();

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
