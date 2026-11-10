import { expect, test } from "@playwright/test";

/** 今天往後 offset 天的 YYYY-MM-DD（瀏覽器的本地日期）。 */
function day(offset: number): string {
  const d = new Date();
  d.setDate(d.getDate() + offset);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

// 2-1 建立行程 → 手動選擇 →【從過去的比較帶入】：選一次比較，再選推薦或次推薦方案，帶入後直接下一步。
// 需要測試登入與方案資料（make seed）。
test("手動選擇時可以從過去的比較帶入方案、保額、目的地與保險期間", async ({ page, request }) => {
  const config = await (await request.get("/api/v1/auth/config")).json();
  test.skip(!config.dev_login, "後端沒有設 DEV_LOGIN_ENABLED=true");
  test.skip(!(await request.get("/api/v1/plans")).ok(), "方案資料沒有載入，先 make seed");

  await page.goto("/login?next=%2F");
  await page.getByLabel("Email").fill(`e2e-incident-import-${Date.now()}@example.com`);
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
  await page.screenshot({ path: "test-results/shots/desktop_2-1_import_list.png" });
  await page.getByTestId("import-comparison").first().click();
  await page.screenshot({ path: "test-results/shots/desktop_2-1_import_plan.png" });

  // 返回再進一次：確認抽屜內可以回到清單
  await page.getByRole("button", { name: "返回" }).click();
  await page.getByTestId("import-comparison").first().click();
  await page.getByTestId("import-plan-alternative").click();

  await expect(page.getByTestId("import-dialog")).toBeHidden();
  await expect(page.getByTestId("import-hint")).toContainText("請依實際購買的保單確認");
  await expect(page.getByTestId("confirm-plan")).toHaveValue(alternative.plan_code);
  await expect(page.getByTestId("confirm-sum-insured")).toHaveValue(
    String(alternative.sum_insured),
  );
  await expect(page.getByLabel("開始日")).toHaveValue(day(7));
  await expect(page.getByLabel("結束日")).toHaveValue(day(11));
  await expect(page.getByTestId("confirm-destination")).toHaveValue("日本");

  // 比較沒有時間：起迄時間變成必填，沒填不能下一步，並列出缺哪兩項
  await expect(page.getByTestId("missing-fields")).toContainText("開始時間、結束時間");
  await expect(page.getByTestId("confirm-continue")).toBeDisabled();
  await page.screenshot({ path: "test-results/shots/desktop_2-1_import_time.png", fullPage: true });
  await page.getByTestId("confirm-start-time").fill("08:30");
  await page.getByTestId("confirm-end-time").fill("22:00");
  await expect(page.getByTestId("missing-fields")).toHaveCount(0);

  // 補完時間就能下一步：建立保單、目的地與時間存進保單
  await page.getByTestId("confirm-continue").click();
  await expect(page).toHaveURL(/\/incident\/new\/[0-9a-f-]{36}$/);
  await expect(page.getByTestId("start-form")).toBeVisible();
  const policies = await (await page.request.get("/api/v1/policies")).json();
  expect(policies[0].destination).toBe("日本");
  expect(policies[0].start_date).toBe(day(7));
});
