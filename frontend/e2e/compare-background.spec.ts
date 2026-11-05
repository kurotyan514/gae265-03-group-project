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

  // 日期選擇器只能選有效範圍：出發日從今天起，回程日是 4～10 天
  await expect(page.getByLabel("出發日")).toHaveAttribute("min", day(0));
  await expect(page.getByLabel("回程日")).toHaveAttribute("min", day(10));
  await expect(page.getByLabel("回程日")).toHaveAttribute("max", day(16));

  for (const age of ["14", "81", "30.5"]) {
    await page.getByLabel("年齡").fill(age);
    await expect(page.getByText("年齡請填 15～80 的整數。")).toBeVisible();
    await expect(next).toBeDisabled();
  }

  // 非數字要逐字輸入，fill 不接受
  for (const age of ["abc", "1e"]) {
    await page.getByLabel("年齡").clear();
    await page.getByLabel("年齡").pressSequentially(age);
    await expect(page.getByText("年齡請填 15～80 的整數。")).toBeVisible();
    await expect(next).toBeDisabled();
  }
});

// 整條 wizard：1-2 選的在意事項與補充說明在上一步、下一步、重新整理之間都留著，最後到 1-3。
test("1-1 → 1-2 → 上一步 → 下一步 → 重新整理，資料都在，最後到推薦方案", async ({ page }) => {
  await login(page, "e2e-compare-concerns@example.com");

  await page.getByRole("link", { name: /出發前：幫我選方案/ }).click();
  await page.getByLabel("目的地").selectOption("日本");
  await page.getByLabel("出發日").fill(day(7));
  await page.getByLabel("回程日").fill(day(11));
  await page.getByLabel("年齡").fill("30");
  await page.getByRole("button", { name: "下一步" }).click();
  await expect(page).toHaveURL(/\/compare\/[0-9a-f-]{36}\/concerns$/);

  await expect(page.getByText("這趟旅行你最擔心什麼？依重要程度點選，最多 3 項。")).toBeVisible();
  await page.getByRole("button", { name: /^生病或受傷就醫/ }).click();
  await page.getByRole("button", { name: /^班機延誤/ }).click();
  await page.getByLabel("其他在意的事（選填）").fill("會去滑雪");

  await page.getByRole("button", { name: "上一步" }).click();
  await expect(page).toHaveURL(/\/background$/);
  await expect(page.getByLabel("目的地")).toHaveValue("日本");
  await expect(page.getByLabel("出發日")).toHaveValue(day(7));
  await expect(page.getByLabel("回程日")).toHaveValue(day(11));
  await expect(page.getByLabel("年齡")).toHaveValue("30");

  await page.getByRole("button", { name: "下一步" }).click();
  await expect(page).toHaveURL(/\/concerns$/);
  for (const reload of [false, true]) {
    if (reload) await page.reload();
    await expect(page.getByRole("button", { name: /^生病或受傷就醫/ })).toHaveAccessibleName(
      "生病或受傷就醫 第 1 順位",
    );
    await expect(page.getByRole("button", { name: /^班機延誤/ })).toHaveAccessibleName(
      "班機延誤 第 2 順位",
    );
    await expect(page.getByLabel("其他在意的事（選填）")).toHaveValue("會去滑雪");
  }

  await page.getByRole("button", { name: "下一步" }).click();
  await expect(page).toHaveURL(/\/result$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("推薦方案");
});

// 依點選順序編號；取消後後面往前補；選滿 3 項其他不能點；沒選不能下一步；補充說明最多 200 字。
test("1-2 的點選順序、取消補位、最多 3 項與補充說明字數", async ({ page }) => {
  await login(page, "e2e-compare-concerns-rules@example.com");
  await page.goto("/compare/new");
  await page.getByLabel("目的地").selectOption("美國");
  await page.getByLabel("出發日").fill(day(7));
  await page.getByLabel("回程日").fill(day(10));
  await page.getByLabel("年齡").fill("30");
  await page.getByRole("button", { name: "下一步" }).click();
  await expect(page).toHaveURL(/\/concerns$/);

  const card = (name: string) => page.getByRole("button", { name: new RegExp(`^${name}`) });
  const next = page.getByRole("button", { name: "下一步" });
  await expect(next).toBeDisabled();

  for (const name of ["行李延誤", "證件遺失", "信用卡盜刷"]) await card(name).click();
  await expect(next).toBeEnabled();
  await expect(card("班機延誤")).toBeDisabled();
  await expect(card("信用卡盜刷")).toHaveAccessibleName("信用卡盜刷 第 3 順位");

  await card("行李延誤").click();
  await expect(card("行李延誤")).toHaveAccessibleName("行李延誤");
  await expect(card("行李延誤")).toHaveAttribute("aria-pressed", "false");
  await expect(card("證件遺失")).toHaveAccessibleName("證件遺失 第 1 順位");
  await expect(card("信用卡盜刷")).toHaveAccessibleName("信用卡盜刷 第 2 順位");
  await expect(card("班機延誤")).toBeEnabled();

  await card("證件遺失").click();
  await card("信用卡盜刷").click();
  await expect(next).toBeDisabled();

  const note = page.getByLabel("其他在意的事（選填）");
  await expect(page.getByText("（0/200）")).toBeVisible();
  await note.fill("滑".repeat(201));
  await expect(note).toHaveValue("滑".repeat(200));
  await expect(page.getByText("（200/200）")).toBeVisible();
});
