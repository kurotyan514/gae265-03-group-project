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

test("1-4 切換情境看試算卡片、開名詞解釋、問答；離開再回來對話是空的", async ({ page }) => {
  await login(page, "e2e-compare-scenarios@example.com");
  await fillTrip(page);
  await page.getByRole("button", { name: /^班機延誤/ }).click();
  await page.getByRole("button", { name: /^突然生病就醫/ }).click();
  await page.getByRole("button", { name: "下一步" }).click();
  await expect(page).toHaveURL(/\/result$/);
  await page.getByRole("link", { name: "情境試算與問答" }).click();
  await expect(page).toHaveURL(/\/scenarios$/);

  await expect(page.getByRole("heading", { level: 1 })).toHaveText("情境試算");
  // 頁籤：在意事項在前加 ★，再依情境表補足 5 個
  const tabs = page.getByRole("tab");
  await expect(tabs).toHaveText([
    "班機延誤 ★",
    "突然生病就醫 ★",
    "行程取消或更改",
    "行李延誤",
    "行李遺失或損壞",
  ]);
  await expect(tabs.first()).toHaveAttribute("aria-selected", "true");

  // 切換頁籤時舊的面板會短暫留著，用頁籤名稱指定面板
  const panel = page.getByRole("tabpanel", { name: "班機延誤 ★" });
  await expect(panel.getByText("試算假設：延誤 8 小時")).toBeVisible();
  await expect(panel.getByText("模板試算・不經 AI")).toBeVisible();
  await expect(panel.getByTestId("conclusion")).toHaveText(
    "延誤 8 小時：富邦國外旅平險-進階型 賠 12,000 元；華南國外旅平險-基礎型 賠 12,000 元。",
  );
  const table = panel.getByRole("table");
  await expect(table.getByRole("columnheader")).toHaveText([
    "",
    /富邦產物 富邦國外旅平險-進階型\s*推薦/,
    "華南產物 華南國外旅平險-基礎型",
  ]);
  await expect(table.getByRole("row", { name: /^以這個故事來說/ })).toContainText("12,000 元");
  await expect(table.getByRole("row", { name: /^最高賠多少/ })).toContainText("12,000 元");
  await expect(panel.getByTestId("basis")).toContainText(
    "富邦產物享樂個人海外旅行不便保險 第 21 條",
  );
  await expect(panel.getByText("僅為依情境假設的試算，實際以保險公司審核為準。")).toBeVisible();

  // 切換頁籤就換卡片
  await page.getByRole("tab", { name: "行李延誤" }).click();
  const luggage = page.getByRole("tabpanel", { name: "行李延誤" });
  await expect(luggage.getByText("試算假設：行李延誤 20 小時")).toBeVisible();
  await expect(luggage.getByTestId("conclusion")).toContainText("行李延誤 20 小時：");
  await page.getByRole("tab", { name: "班機延誤 ★" }).click();

  // 名詞解釋：鍵盤開啟、Esc 關閉；「定額」也能點
  const dialog = page.getByRole("dialog");
  const benefit = table.getByRole("button", { name: "班機延誤保險(定額給付-累進式)" }).first();
  await benefit.focus();
  await page.keyboard.press("Enter");
  await expect(dialog.getByRole("heading")).toHaveText("班機延誤保險(定額給付-累進式)");
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(benefit).toBeFocused();
  await table.getByRole("button", { name: "定額", exact: true }).first().click();
  await expect(dialog.getByRole("heading")).toHaveText("定額");
  await dialog.getByRole("button", { name: "關閉" }).click();
  await expect(dialog).toBeHidden();

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

test("沒有推薦時開 1-4 會導回 1-2", async ({ page }) => {
  await login(page, "e2e-compare-scenarios-empty@example.com");
  await fillTrip(page);
  const id = page.url().split("/").at(-2);
  await page.goto(`/compare/${id}/scenarios`);
  await expect(page).toHaveURL(new RegExp(`/compare/${id}/concerns$`));
});
