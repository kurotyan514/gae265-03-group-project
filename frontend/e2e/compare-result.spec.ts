import { expect, type Page, test } from "@playwright/test";

// 推薦結果依開發資料庫的 seed（make seed）：6 天「班機延誤 → 生病或受傷就醫」。

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
  await page.getByRole("button", { name: /^生病或受傷就醫/ }).click();
  await page.getByRole("button", { name: "下一步" }).click();
  await expect(page).toHaveURL(/\/result$/);

  await expect(page.getByRole("heading", { level: 1 })).toHaveText("推薦方案");
  // 2026/07/05～07/10：回程跨年才寫年份
  const ret = day(12).startsWith(day(7).slice(0, 4)) ? day(12).slice(5) : day(12);
  const range = `${day(7)}～${ret}`.replaceAll("-", "/");
  await expect(page.getByText(`日本 ・ ${range} ・ 6 天 ・ 30 歲`)).toBeVisible();
  const rec = page.getByRole("region", { name: "推薦", exact: true });
  const alt = page.getByRole("region", { name: "次推薦", exact: true });
  await expect(rec.getByRole("heading")).toHaveText("富邦國外旅平險-進階型");
  await expect(rec.getByText("985 元／6 天")).toBeVisible();
  await expect(alt.getByRole("heading")).toHaveText("華南國外旅平險-基礎型");
  await expect(alt.getByText("429 元／6 天")).toBeVisible();
  await expect(alt.getByText("推薦保額 300 萬")).toBeVisible();
  await expect(alt.getByRole("option", { name: "300 萬（推薦）" })).toBeAttached();
  await expect(alt.getByRole("link", { name: "前往易安網投保 ↗" })).toHaveAttribute(
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
  await expect(table.getByRole("rowheader").first()).toContainText("班機延誤你在意");
  await expect(table.getByRole("button", { name: "身故" })).toBeVisible();
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
  await expect(alt.getByText("594 元／6 天")).toBeVisible();
  await expect(
    table.getByRole("columnheader", { name: /華南國外旅平險-基礎型・500 萬/ }),
  ).toBeVisible();
  await expect(rec.getByText("985 元／6 天")).toBeVisible();
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

test("沒有在意事項時開 1-3 會導回 1-2", async ({ page }) => {
  await login(page, "e2e-compare-result-empty@example.com");
  await fillTrip(page);
  const id = page.url().split("/").at(-2);
  await page.goto(`/compare/${id}/result`);
  await expect(page).toHaveURL(new RegExp(`/compare/${id}/concerns$`));
});
