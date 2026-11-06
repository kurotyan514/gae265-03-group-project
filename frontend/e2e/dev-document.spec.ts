import { expect, test } from "@playwright/test";

const SLOW = 30_000;

// 文件辨識測試台（/dev/document）：用 6 號真正的程式逐步辨識範例文件，Drive 是假的。
// 不需要登入、不需要 make seed。
test("文件辨識測試台：登機證加機票兩份到齊，待辦才勾起來", async ({ page }) => {
  await page.goto("/dev/document");

  // 第一份：登機證，一步一步看
  await page.getByRole("button", { name: "登機證", exact: true }).click();
  await expect(page.getByTestId("step-read")).toBeVisible({ timeout: SLOW });
  await expect(page.getByTestId("step-privacy")).toHaveCount(0);
  await page.getByTestId("next").click();
  await expect(page.getByTestId("step-privacy")).toContainText("〔姓名〕");
  // 每一步右下角也有「下一步」，不用捲回上面
  await page.getByTestId("next-bottom").click();
  await expect(page.getByTestId("step-classify")).toContainText("重點：文件代碼 D02");
  await page.getByRole("button", { name: "全部顯示" }).click();
  await expect(page.getByTestId("result")).toContainText("結果：通過");
  await expect(page.getByTestId("result")).toContainText("還缺機票");
  const d02 = page.getByRole("checkbox", { name: "完成 機票及登機證，或航空業者出具的搭機證明" });
  await expect(d02).not.toBeChecked();
  await expect(page.getByTestId("lack")).toContainText("還差機票");

  // 第二份：電子機票，兩份到齊才勾待辦；檔名序號變成 _2
  await page.getByRole("button", { name: "電子機票", exact: true }).click();
  await page.getByRole("button", { name: "全部顯示" }).click({ timeout: SLOW });
  await expect(page.getByTestId("result")).toContainText("已自動勾起來");
  await expect(page.getByTestId("result")).toContainText("_2.pdf");
  await expect(page.getByTestId("passed")).toContainText("D02 機票");
  await expect(d02).toBeChecked();
  await expect(page.getByTestId("lack")).toHaveCount(0);
  await expect(page.getByTestId("result-row")).toHaveCount(2);
});

test("文件辨識測試台：自己上傳檔案，每一步顯示這次實際的輸入與輸出", async ({ page }) => {
  await page.goto("/dev/document");
  await page.getByTestId("file").setInputFiles("../backend/app/agents/document/samples/delay.pdf");
  await page.getByRole("button", { name: "全部顯示" }).click({ timeout: SLOW });

  // 認出種類：列出這份文件實際命中的關鍵字與分數
  await expect(page.getByTestId("out-classify")).toContainText("「班機延誤」×2");
  // 遮個資：遮過的全文裡看不到假姓名
  await expect(page.getByTestId("step-privacy")).toContainText("〔姓名〕");
  await expect(page.getByTestId("step-privacy")).not.toContainText("陳怡君");
  // 檢查內容：列出符合規則的那幾行
  await expect(page.getByTestId("out-check")).toContainText("10:30");
  // 存檔：雲端收到的檔案指紋和上傳的一樣（✓）
  await expect(page.getByTestId("out-save")).toContainText("✓");
  await expect(page.getByTestId("result")).toContainText("結果：通過");
});

test("文件辨識測試台：從待辦的「上傳」傳檔，旁邊的＋可以放大", async ({ page }) => {
  await page.goto("/dev/document");
  await expect(page.getByTestId("pick")).toHaveText("＋ 選擇檔案上傳");
  await expect(page.getByText("事故當下")).toBeVisible();
  await expect(page.getByText("回國後整理")).toBeVisible();

  // 從「填寫理賠申請書」的「上傳」按鈕傳富邦申請書
  const chooser = page.waitForEvent("filechooser");
  await page.getByTestId("todo-upload").last().click();
  await (await chooser).setFiles("../backend/app/agents/document/samples/claim_form.pdf");
  await expect(page.getByRole("checkbox", { name: "完成 填寫理賠申請書" })).toBeChecked({
    timeout: SLOW,
  });

  // 待辦上的檔案旁邊有＋，點了全螢幕放大，按關閉收起來
  await page.getByTestId("passed").getByRole("button", { name: /^放大/ }).click();
  await expect(page.getByTestId("zoom")).toBeVisible();
  await page.getByRole("button", { name: "✕ 關閉" }).click();
  await expect(page.getByTestId("zoom")).toHaveCount(0);
});

test("文件辨識測試台：沒登入時只能用假雲端，並說明原因", async ({ page }) => {
  await page.goto("/dev/document");
  const choice = page.getByTestId("drive-choice");
  await expect(choice.getByRole("checkbox", { name: "存到我的真 Google Drive" })).toBeDisabled();
  await expect(page.getByTestId("drive-reason")).toContainText("只能用假雲端");

  await page.getByRole("button", { name: "延誤證明", exact: true }).click();
  await page.getByRole("button", { name: "全部顯示" }).click({ timeout: SLOW });
  await expect(page.getByTestId("result-drive")).toContainText("展示用的假雲端");
  await expect(page.getByTestId("step-save")).toContainText("存到 Drive（展示用的假雲端）");
});
