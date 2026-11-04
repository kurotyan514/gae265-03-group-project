import { expect, type Page, test } from "@playwright/test";

/** 今天往後 offset 天的 YYYY-MM-DD（瀏覽器的本地日期）。 */
function day(offset: number): string {
  const d = new Date();
  d.setDate(d.getDate() + offset);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

async function login(page: Page, email: string) {
  await page.goto("/login?next=%2F");
  await page.getByLabel("Email").fill(email);
  await page.getByRole("button", { name: "測試登入" }).click();
  await expect(page).toHaveURL(/\/$/);
}

test.beforeEach(async ({ request }) => {
  const config = await (await request.get("/api/v1/auth/config")).json();
  test.skip(!config.dev_login, "後端沒有設 DEV_LOGIN_ENABLED=true");
});

// 首頁 → 1-1 填寫 → 下一步建立紀錄並到 1-2；回到 1-1 帶入已存的資料，修改後存檔，重新整理還在。
test("填完 1-1 按下一步會建立比較紀錄，回來時帶入並可修改", async ({ page }) => {
  await login(page, "e2e-compare-bg@example.com");

  await page.getByRole("link", { name: /出發前：幫我選方案/ }).click();
  await expect(page).toHaveURL(/\/compare\/new$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("這趟旅程");
  await expect(page.getByText("選好兩個日期後顯示天數")).toBeVisible();

  await page.getByLabel("目的地").selectOption("日本");
  await page.getByLabel("出發日").fill(day(7));
  await page.getByLabel("回程日").fill(day(11));
  await page.getByLabel("年齡").fill("30");
  await expect(page.getByText("共 5 天")).toBeVisible();

  await page.getByRole("button", { name: "下一步" }).click();
  await expect(page).toHaveURL(/\/compare\/[0-9a-f-]{36}\/concerns$/);
  const id = page.url().split("/").at(-2);

  await page.goto(`/compare/${id}/background`);
  await expect(page.getByLabel("目的地")).toHaveValue("日本");
  await expect(page.getByLabel("出發日")).toHaveValue(day(7));
  await expect(page.getByLabel("回程日")).toHaveValue(day(11));
  await expect(page.getByLabel("年齡")).toHaveValue("30");

  await page.getByLabel("目的地").selectOption("韓國");
  await page.getByLabel("年齡").fill("45");
  await page.getByRole("button", { name: "下一步" }).click();
  await expect(page).toHaveURL(new RegExp(`/compare/${id}/concerns$`));

  await page.goto(`/compare/${id}/background`);
  await page.reload();
  await expect(page.getByLabel("目的地")).toHaveValue("韓國");
  await expect(page.getByLabel("年齡")).toHaveValue("45");
});

// 不合規則時顯示原因，「下一步」不能按。
test("1-1 的日期、天數與年齡不合規則時顯示原因且不能按下一步", async ({ page }) => {
  await login(page, "e2e-compare-bg-invalid@example.com");
  await page.goto("/compare/new");

  const next = page.getByRole("button", { name: "下一步" });
  await page.getByLabel("目的地").selectOption("美國");
  await page.getByLabel("年齡").fill("30");
  await expect(next).toBeDisabled();

  const cases: [string, string, string][] = [
    [day(-1), day(4), "出發日要從今天起。"],
    [day(7), day(6), "回程日不能早於出發日。"],
    [day(7), day(9), "旅遊天數最短 4 天。"],
    [day(7), day(17), "旅遊天數最長 10 天。"],
  ];
  for (const [depart, ret, message] of cases) {
    await page.getByLabel("出發日").fill(depart);
    await page.getByLabel("回程日").fill(ret);
    await expect(page.getByText(message)).toBeVisible();
    await expect(next).toBeDisabled();
  }

  await page.getByLabel("出發日").fill(day(7));
  await page.getByLabel("回程日").fill(day(10));
  await expect(next).toBeEnabled();

  for (const age of ["14", "81", "30.5"]) {
    await page.getByLabel("年齡").fill(age);
    await expect(page.getByText("年齡請填 15～80 的整數。")).toBeVisible();
    await expect(next).toBeDisabled();
  }
});
