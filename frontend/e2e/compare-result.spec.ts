import { expect, type Page, test } from "@playwright/test";

// 推薦結果依開發資料庫的 seed（make seed）：6 天「班機延誤 → 突然生病就醫」。

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

test("1-3 顯示推薦、依據、比較表與名詞解釋；改次推薦保額後重新整理還在", async ({ page }) => {
  await login(page, "e2e-compare-result@example.com");
  await fillTrip(page);
  await page.getByRole("button", { name: /^班機延誤/ }).click();
  await page.getByRole("button", { name: /^突然生病就醫/ }).click();
  await page.getByRole("button", { name: "下一步" }).click();
  await expect(page).toHaveURL(/\/result$/);

  await expect(page.getByRole("heading", { level: 1 })).toHaveText("推薦方案與比較表");
  // 2026/07/05～07/10：回程跨年才寫年份
  const ret = day(12).startsWith(day(7).slice(0, 4)) ? day(12).slice(5) : day(12);
  const range = `${day(7)}～${ret}`.replaceAll("-", "/");
  await expect(page.getByText(`日本 · ${range} · 6 天 · 30 歲`)).toBeVisible();
  const rec = page.getByRole("region", { name: "推薦", exact: true });
  const alt = page.getByRole("region", { name: "次推薦", exact: true });
  await expect(rec.getByRole("heading")).toHaveText("富邦國外旅平險-進階型");
  await expect(rec.getByText("6 天 985 元")).toBeVisible();
  await expect(alt.getByRole("heading")).toHaveText("華南國外旅平險-基礎型");
  await expect(alt.getByText("6 天 429 元")).toBeVisible();
  await expect(alt.getByLabel("推薦保額")).toHaveValue("3000000");
  await expect(page.getByText("示意資料")).toHaveCount(0);
  await expect(alt.getByRole("option", { name: "300 萬（推薦）" })).toBeAttached();
  await expect(alt.getByRole("link", { name: "前往保險公司官網投保 ↗" })).toHaveAttribute(
    "target",
    "_blank",
  );
  const reason =
    "你最在意「班機延誤」，推薦方案在這一項是 9,000 元，次推薦是 6,000 元；保費多 556 元。";
  await expect(page.getByTestId("reason")).toHaveText(reason);

  // 推薦依據
  await page.getByRole("button", { name: "看推薦依據" }).click();
  await expect(page.getByTestId("basis").getByRole("listitem")).toHaveCount(3);
  await page.getByRole("button", { name: "收合推薦依據" }).click();
  await expect(page.getByTestId("basis")).toBeHidden();

  // 比較表：預設只有在意的列與身故
  const table = page.getByRole("table");
  await expect(table.getByRole("rowheader").first()).toContainText("班機延誤你在意 1");
  await expect(table.getByRole("button", { name: "身故" })).toBeVisible();
  await expect(table.getByRole("button", { name: "意外醫療" })).toBeVisible();
  await expect(table.getByRole("button", { name: "責任保險" })).toBeHidden();
  await page.getByRole("button", { name: "看全部項目" }).click();
  await expect(table.getByRole("button", { name: "責任保險" })).toBeVisible();
  await page.getByRole("button", { name: "收合" }).click();
  await expect(table.getByRole("button", { name: "責任保險" })).toBeHidden();

  // 名詞解釋：鍵盤開啟，Esc 與「關閉」都能關
  await table.getByRole("button", { name: "班機延誤" }).focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading")).toHaveText("班機延誤");
  await expect(dialog).toContainText("班機延誤保險(定額給付-累進式)");
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(table.getByRole("button", { name: "班機延誤" })).toBeFocused();
  await table.getByRole("button", { name: "身故" }).click();
  await dialog.getByRole("button", { name: "關閉" }).click();
  await expect(dialog).toBeHidden();

  // 改次推薦保額：只有次推薦卡片與那一欄改變
  await alt.getByLabel("保額").selectOption({ label: "500 萬" });
  await expect(alt.getByText("6 天 594 元")).toBeVisible();
  await expect(alt.getByLabel("保額（已自行調整）")).toHaveValue("5000000");
  // 欄位標題不寫保額
  await expect(
    table.getByRole("columnheader", { name: /華南國外旅平險-基礎型/ }),
  ).not.toContainText("萬");
  await expect(rec.getByText("6 天 985 元")).toBeVisible();
  await expect(page.getByTestId("reason")).toHaveText(reason);
  await page.reload();
  await expect(alt.getByLabel("保額")).toHaveValue("5000000");

  await page.getByRole("link", { name: "上一步" }).click();
  await expect(page).toHaveURL(/\/concerns$/);
  await page.getByRole("button", { name: "下一步" }).click();
  await expect(page).toHaveURL(/\/result$/);
  await expect(alt.getByLabel("保額")).toHaveValue("5000000");
  await page.getByRole("link", { name: "完成" }).click();
  await expect(page).toHaveURL(/\/$/);
});

test("手機寬度（390px）下 1-3 沒有橫向捲動，比較表列名獨佔一列、推薦與次推薦並排", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page, "e2e-compare-result-mobile@example.com");
  await fillTrip(page);
  await page.getByRole("button", { name: /^班機延誤/ }).click();
  await page.getByRole("button", { name: "下一步" }).click();
  await expect(page).toHaveURL(/\/result$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("推薦方案與比較表");
  await page.getByRole("button", { name: "看全部項目" }).click();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(overflow).toBe(false);
  const row = page.getByRole("table").getByRole("row").nth(1); // 0 是表頭
  const head = await row.getByRole("rowheader").boundingBox();
  const cells = await row.getByRole("cell").all();
  const a = await cells[0]?.boundingBox();
  const b = await cells[1]?.boundingBox();
  expect(head && a && b && a.y > head.y && a.y === b.y && b.x > a.x).toBeTruthy();
});

test("沒有在意事項時開 1-3 會導回 1-2", async ({ page }) => {
  await login(page, "e2e-compare-result-empty@example.com");
  await fillTrip(page);
  const id = page.url().split("/").at(-2);
  await page.goto(`/compare/${id}/result`);
  await expect(page).toHaveURL(new RegExp(`/compare/${id}/concerns$`));
});

test("1-3 比較表把疾病醫療合成一列，緊急救援與責任保險標「你在意」，意外醫療不標", async ({
  page,
}) => {
  await login(page, "e2e-compare-merged-rows@example.com");
  await fillTrip(page);
  await page.getByRole("button", { name: /^需要緊急送醫或家屬趕來/ }).click();
  await page.getByRole("button", { name: /^突然生病就醫/ }).click();
  await page.getByRole("button", { name: /^不小心弄傷別人或弄壞東西/ }).click();
  await page.getByRole("button", { name: "下一步" }).click();
  await expect(page).toHaveURL(/\/result$/);

  const table = page.getByRole("table");
  const heads = table.getByRole("rowheader");
  await expect(heads.nth(0)).toContainText("緊急救援你在意");
  await expect(heads.nth(1)).toContainText("海外突發疾病醫療你在意");
  await expect(heads.nth(2)).toContainText("責任保險你在意");
  await expect(heads.nth(3)).toContainText("身故");
  await expect(heads.nth(4)).toContainText("意外醫療");
  await expect(heads.nth(4)).not.toContainText("你在意");

  await page.getByRole("button", { name: "看全部項目" }).click();
  await expect(table.getByRole("rowheader", { name: /海外疾病/ })).toHaveCount(0);

  // 合併列分別列出住院、門診、急診
  await table.getByRole("button", { name: "海外突發疾病醫療" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading")).toHaveText("海外突發疾病醫療");
  for (const kind of ["住院", "門診", "急診"]) {
    await expect(dialog).toContainText(`海外突發疾病${kind}醫療`);
  }
});
