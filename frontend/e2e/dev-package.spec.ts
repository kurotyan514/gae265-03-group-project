import { expect, type Page, test } from "@playwright/test";

// 打包寄送測試台（/dev/package）：用 7 號真正的程式，從虛構的範例事件產生送件信。
// 不需要登入、不需要 make seed、不連 Google（Google 授權是模擬的；預設 Drive 已授權、Gmail 還沒）。

/** 按「好險有你小助理幫我送出」，在 Gmail 的說明視窗按同意（模擬授權），進到預覽。 */
async function assistWithGoogle(page: Page) {
  await page.getByRole("button", { name: "好險有你小助理幫我送出" }).click();
  const consent = page.getByTestId("google-consent");
  await expect(consent).toContainText("Gmail");
  await page.getByTestId("google-consent-continue").click();
  await expect(consent).toHaveCount(0);
}

const CLOSED = "此事件已結案，不能再新增狀況或修改。";

test("打包寄送測試台：資料都抓不到時，空格都變成輸入框，列出十項，填完前不能寄出", async ({
  page,
}) => {
  await page.goto("/dev/package");
  await page.getByRole("button", { name: "資料都抓不到", exact: true }).click();
  await assistWithGoogle(page);

  // 信件裡每個「（請填寫＋項目）」都變成輸入框（內文十處，主旨另有保險期間）
  const body = page.getByTestId("letter-body");
  await expect(body.getByRole("textbox", { name: "被保險人姓名" })).toHaveAttribute(
    "placeholder",
    "（請填寫被保險人姓名）",
  );
  await expect(body.getByTestId("blank")).toHaveCount(10);
  await expect(page.getByTestId("letter-subject").getByTestId("blank")).toHaveCount(1);

  // 預覽頁列出要填的項目（重複的只列一次），還有要填的就不能寄出
  const missing = page.getByTestId("missing");
  await expect(missing).toContainText("還有 10 項要填寫");
  await expect(missing.getByTestId("missing-item")).toHaveCount(10);
  await expect(missing).toContainText("聯絡電話");
  await expect(page.getByRole("button", { name: "寄出", exact: true })).toBeDisabled();
});

test("打包寄送測試台：資料齊全時只剩平台沒有的三項，填完就能寄出並結案", async ({ page }) => {
  await page.goto("/dev/package");
  await page.getByRole("button", { name: "資料齊全", exact: true }).click();
  await assistWithGoogle(page);

  await expect(page.getByTestId("letter-subject")).toContainText("富邦國外旅平險-進階型");
  await expect(page.getByTestId("letter-body").getByTestId("blank")).toHaveCount(3);
  await expect(page.getByTestId("attachment")).toHaveCount(3);

  await expect(page.getByTestId("missing").getByTestId("missing-item")).toHaveText([
    "被保險人姓名",
    "保單號碼",
    "聯絡電話",
  ]);
  const send = page.getByRole("button", { name: "寄出", exact: true });
  await expect(send).toBeDisabled();

  await page.getByRole("textbox", { name: "被保險人姓名" }).fill("王小明");
  await page.getByRole("textbox", { name: "保單號碼" }).fill("A123456789");
  await page.getByRole("textbox", { name: "聯絡電話" }).fill("0912345678");
  await page.getByRole("textbox", { name: "收件者" }).fill("claims@example.com");
  await expect(page.getByTestId("missing")).toHaveCount(0);
  await send.click();

  // 已經授權過 Gmail，不用再問；寄出後結案，看得到寄出的信
  await expect(page.getByTestId("google-consent")).toHaveCount(0);
  const closed = page.getByTestId("closed");
  await expect(closed).toContainText("已用你的 Gmail 寄給保險公司");
  await expect(closed).toContainText(CLOSED);
  await expect(closed.getByTestId("letter-body")).toContainText("王小明");
  await expect(closed.getByTestId("letter-body")).not.toContainText("請填寫");
});

test("打包寄送測試台：選了範例先問要不要幫忙寄，還沒看到信", async ({ page }) => {
  await page.goto("/dev/package");
  await page.getByRole("button", { name: "資料齊全", exact: true }).click();

  await expect(page.getByText("要由我們用你的 Gmail 幫你寄給保險公司嗎？")).toBeVisible();
  await expect(page.getByRole("button", { name: "我自己處理就好" })).toBeVisible();
  await expect(page.getByRole("button", { name: "好險有你小助理幫我送出" })).toBeVisible();
  await expect(page.getByTestId("letter-body")).toHaveCount(0);
});

test("打包寄送測試台：Drive 失效時先問 Drive 再問 Gmail", async ({ page }) => {
  await page.goto("/dev/package");
  await page.getByRole("checkbox", { name: "模擬：Google Drive 已授權" }).uncheck();
  await page.getByRole("button", { name: "資料齊全", exact: true }).click();

  await page.getByRole("button", { name: "好險有你小助理幫我送出" }).click();
  const consent = page.getByTestId("google-consent");
  await expect(consent).toContainText("Google Drive");
  await page.getByTestId("google-consent-continue").click();
  await expect(consent).toContainText("Gmail");
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

test("打包寄送測試台：Gmail 按先不要也進預覽，寄出時再問，填的內容不會不見", async ({ page }) => {
  await page.goto("/dev/package");
  await page.getByRole("button", { name: "資料齊全", exact: true }).click();

  await page.getByRole("button", { name: "好險有你小助理幫我送出" }).click();
  await page.getByTestId("google-consent-cancel").click();
  await expect(page.getByTestId("letter-body")).toBeVisible();

  await page.getByRole("textbox", { name: "被保險人姓名" }).fill("王小明");
  await page.getByRole("textbox", { name: "保單號碼" }).fill("A123456789");
  await page.getByRole("textbox", { name: "聯絡電話" }).fill("0912345678");
  await page.getByRole("textbox", { name: "收件者" }).fill("claims@example.com");
  const send = page.getByRole("button", { name: "寄出", exact: true });

  // 寄出時還沒授權 Gmail：再問一次；按先不要就留在預覽，填的內容還在
  await send.click();
  await expect(page.getByTestId("google-consent")).toContainText("Gmail");
  await page.getByTestId("google-consent-cancel").click();
  await expect(page.getByRole("textbox", { name: "被保險人姓名" })).toHaveValue("王小明");
  await expect(page.getByTestId("closed")).toHaveCount(0);

  // 再按寄出、同意，才寄出並結案
  await send.click();
  await page.getByTestId("google-consent-continue").click();
  await expect(page.getByTestId("closed")).toContainText("已用你的 Gmail 寄給保險公司");
});

test("打包寄送測試台：同一個項目填一次，主旨和內文一起更新", async ({ page }) => {
  await page.goto("/dev/package");
  await page.getByRole("button", { name: "資料都抓不到", exact: true }).click();
  await assistWithGoogle(page);

  const period = page.getByRole("textbox", { name: "保險期間", exact: true });
  await expect(period).toHaveCount(2);
  await page.getByTestId("letter-subject").getByRole("textbox").fill("2026/8/10–8/14");
  await expect(period.nth(1)).toHaveValue("2026/8/10–8/14");
  await expect(page.getByTestId("missing")).toContainText("還有 9 項要填寫");
});

test("打包寄送測試台：我自己處理就好，先問要不要建立草稿", async ({ page }) => {
  await page.goto("/dev/package");
  await page.getByRole("button", { name: "資料齊全", exact: true }).click();

  await page.getByRole("button", { name: "我自己處理就好" }).click();
  const question = page.getByTestId("draft-question");
  await expect(question).toContainText("需要幫你在 Gmail 建立草稿嗎？");
  await expect(question).toContainText("之後不能再新增狀況或修改");
  await expect(page.getByTestId("google-consent")).toHaveCount(0);
  await expect(page.getByTestId("letter-body")).toHaveCount(0);
});

test("打包寄送測試台：自己處理、不建立草稿，直接結案", async ({ page }) => {
  await page.goto("/dev/package");
  await page.getByRole("button", { name: "資料齊全", exact: true }).click();

  await page.getByRole("button", { name: "我自己處理就好" }).click();
  await page.getByTestId("draft-question").getByRole("button", { name: "取消" }).click();

  const closed = page.getByTestId("closed");
  await expect(closed).toContainText("沒有建立草稿");
  await expect(closed).toContainText(CLOSED);
  await expect(page.getByTestId("google-consent")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "好險有你小助理幫我送出" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "我自己處理就好" })).toHaveCount(0);
});

test("打包寄送測試台：自己處理、建立草稿，Gmail 先不要就回到草稿的問題", async ({ page }) => {
  await page.goto("/dev/package");
  await page.getByRole("button", { name: "資料齊全", exact: true }).click();

  await page.getByRole("button", { name: "我自己處理就好" }).click();
  const question = page.getByTestId("draft-question");
  await question.getByRole("button", { name: "確定" }).click();

  // 要建立草稿得先授權 Gmail；按先不要還沒結案，回到草稿的問題
  await expect(page.getByTestId("google-consent")).toContainText("Gmail");
  await page.getByTestId("google-consent-cancel").click();
  await expect(question).toBeVisible();
  await expect(page.getByTestId("closed")).toHaveCount(0);

  await question.getByRole("button", { name: "確定" }).click();
  await page.getByTestId("google-consent-continue").click();
  const closed = page.getByTestId("closed");
  await expect(closed).toContainText("已在你的 Gmail 建立草稿");
  await expect(closed).toContainText(CLOSED);
});

test("打包寄送測試台：按 Esc 關掉草稿的問題不算結案", async ({ page }) => {
  await page.goto("/dev/package");
  await page.getByRole("button", { name: "資料齊全", exact: true }).click();

  await page.getByRole("button", { name: "我自己處理就好" }).click();
  await expect(page.getByTestId("draft-question")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("draft-question")).toHaveCount(0);
  await expect(page.getByTestId("closed")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "好險有你小助理幫我送出" })).toBeVisible();
});

test("打包寄送測試台：預覽頁顯示寄件者，收件者要自己填", async ({ page }) => {
  await page.goto("/dev/package");
  await page.getByRole("button", { name: "資料齊全", exact: true }).click();
  await assistWithGoogle(page);

  await expect(page.getByTestId("letter-sender")).toHaveText("you@example.com");
  await expect(page.getByRole("textbox", { name: "收件者" })).toHaveValue("");
  await expect(page.getByTestId("recipient-problem")).toHaveText("請填寫收件者");
});

test("打包寄送測試台：收件者沒填或格式不對都不能寄出", async ({ page }) => {
  await page.goto("/dev/package");
  await page.getByRole("button", { name: "資料齊全", exact: true }).click();
  await assistWithGoogle(page);

  // 空格都填完，但還沒填收件者
  await page.getByRole("textbox", { name: "被保險人姓名" }).fill("王小明");
  await page.getByRole("textbox", { name: "保單號碼" }).fill("A123456789");
  await page.getByRole("textbox", { name: "聯絡電話" }).fill("0912345678");
  const send = page.getByRole("button", { name: "寄出", exact: true });
  await expect(send).toBeDisabled();

  const recipient = page.getByRole("textbox", { name: "收件者" });
  await recipient.fill("claims.example.com");
  await expect(page.getByTestId("recipient-problem")).toHaveText("收件者的 email 格式不對");
  await expect(send).toBeDisabled();

  await recipient.fill("claims@example.com");
  await expect(page.getByTestId("recipient-problem")).toHaveCount(0);
  await send.click();

  // 寄出的信看得到寄件者與收件者
  const closed = page.getByTestId("closed");
  await expect(closed.getByTestId("letter-sender")).toHaveText("you@example.com");
  await expect(closed.getByTestId("letter-recipient")).toHaveText("claims@example.com");
});

test("打包寄送測試台：空格沒填完，填了收件者也不能寄出", async ({ page }) => {
  await page.goto("/dev/package");
  await page.getByRole("button", { name: "資料齊全", exact: true }).click();
  await assistWithGoogle(page);

  await page.getByRole("textbox", { name: "收件者" }).fill("claims@example.com");
  await expect(page.getByRole("button", { name: "寄出", exact: true })).toBeDisabled();
});
