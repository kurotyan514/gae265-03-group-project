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
  await page.getByRole("button", { name: "全部顯示" }).click();
  await expect(page.getByTestId("result")).toContainText("結果：通過");
  await expect(page.getByTestId("result")).toContainText("還缺機票");

  // 第二份：電子機票，兩份到齊才勾待辦；檔名序號變成 _2
  await page.getByRole("button", { name: "電子機票" }).click();
  await page.getByRole("button", { name: "全部顯示" }).click({ timeout: SLOW });
  await expect(page.getByTestId("result")).toContainText("已自動勾起來");
  await expect(page.getByTestId("result")).toContainText("_2.pdf");
  await expect(page.getByTestId("passed")).toContainText("D02 機票");
});
