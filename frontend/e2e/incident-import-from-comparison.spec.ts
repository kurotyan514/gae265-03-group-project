import { expect, test } from "@playwright/test";

/** 今天往後 offset 天的 YYYY-MM-DD（瀏覽器的本地日期）。 */
function day(offset: number): string {
  const d = new Date();
  d.setDate(d.getDate() + offset);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

// 出事了 → 選方案與保額 →【從過去比較帶入】：選一次比較，再選推薦或次推薦方案。
// 需要測試登入與方案資料（make seed）。
test("手選保單時可以從過去的比較帶入方案、保額與保險期間", async ({ page, request }) => {
  const config = await (await request.get("/api/v1/auth/config")).json();
  test.skip(!config.dev_login, "後端沒有設 DEV_LOGIN_ENABLED=true");
  test.skip(!(await request.get("/api/v1/plans")).ok(), "方案資料沒有載入，先 make seed");

  await page.goto("/login?next=%2F");
  await page.getByLabel("Email").fill("e2e-incident-import@example.com");
  await page.getByRole("button", { name: "測試登入" }).click();
  await expect(page).toHaveURL(/\/$/);

  // 先做出一筆已推薦的比較
  const created = await page.request.post("/api/v1/comparisons", {
    data: {
      destination: "日本",
      depart_date: day(7),
      return_date: day(11),
      age: 30,
      concerns: ["班機延誤"],
    },
  });
  expect(created.ok()).toBeTruthy();
  const comparison = await created.json();
  const alternative = comparison.recommendation.alternative;

  await page.goto("/incident/new");
  await page.getByTestId("mode-manual").click();
  await page.getByTestId("import-from-comparison").click();
  await page.getByTestId("import-comparison").first().click();

  // 返回再進一次：確認彈窗內可以回到清單
  await page.getByRole("button", { name: "返回" }).click();
  await page.getByTestId("import-comparison").first().click();
  await page.getByTestId("import-plan-alternative").click();

  await expect(page.getByTestId("import-dialog")).toBeHidden();
  await expect(page.getByTestId("import-hint")).toContainText("請依實際購買的保單確認");
  await expect(page.getByTestId("manual-plan")).toHaveValue(alternative.plan_code);
  await expect(page.getByTestId("manual-sum-insured")).toHaveValue(String(alternative.sum_insured));
  await expect(page.getByLabel("保險開始日（選填）")).toHaveValue(day(7));
  await expect(page.getByLabel("保險結束日（選填）")).toHaveValue(day(11));

  // 帶入的內容可以直接建立保單，目的地帶進下一步
  await page.getByTestId("create-manual-policy").click();
  await expect(page.getByTestId("policy")).toBeVisible();
  await expect(page.getByLabel("目的地（選填）")).toHaveValue("日本");
});
