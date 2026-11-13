import { expect, type Page, test } from "@playwright/test";

// 試算依開發資料庫的 seed（make seed）與 scenario_rules.json：6 天「班機延誤 → 突然生病就醫」，
// 推薦富邦國外旅平險-進階型、次推薦華南國外旅平險-基礎型。
// 問答的回答內容看 LLM 供應商（fake 固定回同一句），只檢查有回答。

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

async function fillTrip(page: Page) {
  await page.goto("/compare/new");
  await page.getByLabel("目的地").selectOption("日本");
  await page.getByLabel("出發日").fill(day(7));
  await page.getByLabel("回程日").fill(day(12));
  await page.getByLabel("年齡").fill("30");
  await page.getByRole("button", { name: "下一步" }).click();
  await expect(page).toHaveURL(/\/compare\/[0-9a-f-]{36}\/concerns$/);
}

test.beforeEach(async ({ request }) => {
  const config = await (await request.get("/api/v1/auth/config")).json();
  test.skip(!config.dev_login, "後端沒有設 DEV_LOGIN_ENABLED=true");
});

test("1-4 切換情境看多列試算卡片、問答；離開再回來對話是空的", async ({ page }) => {
  // 問答與條款處理走真的 LLM，單測預設 30 秒會比內部 60 秒的 expect 先逾時
  test.setTimeout(120_000);
  await login(page, "e2e-compare-scenarios@example.com");
  await fillTrip(page);
  await page.getByRole("button", { name: /^班機延誤/ }).click();
  await page.getByRole("button", { name: /^突然生病就醫/ }).click();
  await page.getByRole("button", { name: "下一步" }).click();
  await expect(page).toHaveURL(/\/result$/);
  await page.getByRole("link", { name: "情境試算與問答" }).click();
  await expect(page).toHaveURL(/\/scenarios$/);

  await expect(page.getByRole("heading", { level: 1 })).toHaveText("情境試算與問答");
  // 頁籤：涵蓋在意事項的在前加 ★，其餘照情境表的順序，一律 5 個
  const tabs = page.getByRole("tab");
  await expect(tabs).toHaveText(["航班延誤 ★", "生病住院 ★", "行前取消", "錢包被偷", "騎車撞傷"]);
  await expect(tabs.first()).toHaveAttribute("aria-selected", "true");

  // 切換頁籤時舊的面板會短暫留著，用頁籤名稱指定面板
  const panel = page.getByRole("tabpanel", { name: "航班延誤 ★" });
  await expect(panel.getByText("試算假設：班機延誤 8 小時；行李延誤 20 小時")).toBeVisible();
  await expect(panel.getByTestId("conclusion")).toHaveText(
    "富邦國外旅平險-進階型：班機延誤 賠 12,000 元、行李延誤 賠 6,000 元；華南國外旅平險-基礎型：班機延誤 賠 12,000 元、行李延誤 賠 6,000 元。",
  );
  const table = panel.getByRole("table");
  await expect(table.getByRole("columnheader")).toHaveText([
    "保障項目",
    /推薦富邦產物 富邦國外旅平險-進階型/,
    /次推薦華南產物 華南國外旅平險-基礎型/,
  ]);
  // 多列：每一列各自試算
  await expect(table.getByRole("row")).toHaveCount(3);
  const flight = table.getByRole("row", { name: /^班機延誤\s*定額/ });
  await expect(flight).toContainText("賠 12,000 元");
  await expect(flight).not.toContainText("最高賠多少");
  await expect(flight).not.toContainText("在保障範圍內");
  await expect(table.getByRole("row", { name: /^行李延誤\s*定額/ })).toContainText("賠 6,000 元");
  await expect(panel.getByTestId("note")).toHaveCount(0);
  await expect(panel.getByText("僅為依情境假設的試算，實際以保險公司審核為準。")).toBeVisible();

  // 切換頁籤就換卡片：錢包被偷有 3 列與固定附註；方案沒有的保障顯示「不在保障範圍」
  await page.getByRole("tab", { name: "錢包被偷" }).click();
  const wallet = page.getByRole("tabpanel", { name: "錢包被偷" });
  await expect(wallet.getByRole("row")).toHaveCount(4);
  await expect(wallet.getByRole("row", { name: /^信用卡盜用\s*實支實付/ })).toBeVisible();
  await expect(wallet.getByTestId("note")).toHaveText(
    "附註：背包視為「類似容器」，包內物品可依損失申請，背包本身不賠。",
  );
  await page.getByRole("tab", { name: "騎車撞傷" }).click();
  const crash = page.getByRole("tabpanel", { name: "騎車撞傷" });
  await expect(crash.getByRole("row", { name: /^緊急救援\s*實支實付/ })).toBeVisible();
  await page.getByRole("tab", { name: "航班延誤 ★" }).click();

  // 問答：常見問題
  const chat = page.getByRole("region", { name: "問答" });
  await expect(
    chat.getByText("點下方常見問題，或自己輸入。問答內容不會保存，離開這頁就會清空。"),
  ).toBeVisible();
  await chat.getByRole("button", { name: "班機延誤多久才能賠？" }).click();
  await expect(chat.getByTestId("question")).toHaveText(["班機延誤多久才能賠？"]);
  await expect(chat.getByTestId("answer")).toHaveCount(1, { timeout: 60_000 });
  // 第一次發問後常見問題收起，可用「常見問題」再展開
  await expect(chat.getByRole("button", { name: "兩個方案差在哪？" })).toBeHidden();
  await chat.getByRole("button", { name: "常見問題" }).click();
  await expect(chat.getByRole("button", { name: "兩個方案差在哪？" })).toBeVisible();

  // 問答：自己輸入，有字才能送出、送出後清空
  const input = chat.getByLabel("問題");
  const send = chat.getByRole("button", { name: "送出" });
  await expect(send).toBeDisabled();
  await input.fill("那次推薦呢？");
  const asked = page.waitForRequest(/\/questions$/);
  await send.click();
  // 帶前一輪當 history，後端才能改寫追問
  const body = (await asked).postDataJSON();
  expect(body.question).toBe("那次推薦呢？");
  expect(body.history.map((t: { question: string }) => t.question)).toEqual([
    "班機延誤多久才能賠？",
  ]);
  await expect(input).toHaveValue("");
  await expect(chat.getByTestId("question")).toHaveText(["班機延誤多久才能賠？", "那次推薦呢？"]);
  await expect(chat.getByTestId("answer")).toHaveCount(2, { timeout: 60_000 });

  // 回比較表再進來：對話區是空的
  await page.getByRole("link", { name: "回比較表" }).click();
  await expect(page).toHaveURL(/\/result$/);
  await page.getByRole("link", { name: "情境試算與問答" }).click();
  await expect(page).toHaveURL(/\/scenarios$/);
  await expect(chat.getByTestId("question")).toHaveCount(0);
  await expect(chat.getByRole("button", { name: "兩個方案差在哪？" })).toBeVisible();

  await page.getByRole("link", { name: "完成" }).click();
  await expect(page).toHaveURL(/\/$/);
});

test("手機寬度（390px）下 1-4 沒有橫向捲動；頁籤可橫向捲動", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page, "e2e-compare-scenarios-mobile@example.com");
  await fillTrip(page);
  await page.getByRole("button", { name: /^班機延誤/ }).click();
  await page.getByRole("button", { name: "下一步" }).click();
  await expect(page).toHaveURL(/\/result$/);
  await page.getByRole("link", { name: "情境試算與問答" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("情境試算與問答");
  await expect(page.getByTestId("conclusion")).toBeVisible();
  const overflow = () =>
    page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    );
  expect(await overflow()).toBe(false);
  const list = page.getByRole("tablist");
  expect(await list.evaluate((el) => el.scrollWidth > el.clientWidth)).toBe(true);
  await page.getByRole("tab").last().click();
  expect(await overflow()).toBe(false);
});

test("1-2 選新的在意事項 → 1-3 標「你在意」→ 1-4 ★ 排前 → 點短名稱與給付方式開解釋", async ({
  page,
}) => {
  await login(page, "e2e-compare-scenarios-flow@example.com");
  await fillTrip(page);
  // 選的順序就是重要程度：1 突然生病就醫、2 不小心弄傷別人、3 需要緊急送醫
  await page.getByRole("button", { name: /^突然生病就醫/ }).click();
  await page.getByRole("button", { name: /^不小心弄傷別人或弄壞東西/ }).click();
  await page.getByRole("button", { name: /^需要緊急送醫或家屬趕來/ }).click();
  await page.getByRole("button", { name: "下一步" }).click();
  await expect(page).toHaveURL(/\/result$/);

  // 1-3：合併列、責任保險與選了才出現的緊急救援都標「你在意」
  const heads = page.getByRole("table").getByRole("rowheader");
  await expect(heads.filter({ hasText: "海外突發疾病醫療你在意" })).toHaveCount(1);
  await expect(heads.filter({ hasText: "責任保險你在意" })).toHaveCount(1);
  await expect(heads.filter({ hasText: "緊急救援你在意" })).toHaveCount(1);

  // 1-4：有 ★ 的排前面，依涵蓋的在意事項中排名最前的排序
  await page.getByRole("link", { name: "情境試算與問答" }).click();
  await expect(page.getByRole("tab")).toHaveText([
    "生病住院 ★",
    "騎車撞傷 ★",
    "航班延誤",
    "行前取消",
    "錢包被偷",
  ]);

  // 短名稱：白話說明，加上兩個方案各自採用的保障項目
  const panel = page.getByRole("tabpanel", { name: "生病住院 ★" });
  await panel.getByRole("button", { name: "海外突發疾病醫療" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading")).toHaveText("海外突發疾病醫療");
  await expect(dialog).toContainText("富邦國外旅平險-進階型");
  await expect(dialog).toContainText("次推薦｜富邦產物 富邦國外旅平險-基礎型");
  await expect(dialog).toContainText("海外突發疾病住院");
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();

  // 給付方式：另一個說明
  await panel.getByRole("button", { name: "實支實付" }).click();
  await expect(dialog.getByRole("heading")).toHaveText("實支實付");
  await dialog.getByRole("button", { name: "關閉" }).click();
  await expect(dialog).toBeHidden();

  // 有條款依據的列（班機延誤）顯示「{險種名} 第 N 條」
  await page.getByRole("tab", { name: "航班延誤" }).click();
  await page
    .getByRole("tabpanel", { name: "航班延誤" })
    .getByRole("button", { name: "班機延誤" })
    .click();
  await expect(dialog).toContainText(/條款依據：.+ 第 \d+ 條/);
  await dialog.getByRole("button", { name: "關閉" }).click();
});

test("沒有推薦時開 1-4 會導回 1-2", async ({ page }) => {
  await login(page, "e2e-compare-scenarios-empty@example.com");
  await fillTrip(page);
  const id = page.url().split("/").at(-2);
  await page.goto(`/compare/${id}/scenarios`);
  await expect(page).toHaveURL(new RegExp(`/compare/${id}/concerns$`));
});
