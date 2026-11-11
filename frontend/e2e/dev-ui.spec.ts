import { expect, test } from "@playwright/test";

// 功能二共用元件預覽（#215）：/dev/ui 只在非 production 有，不需要登入。
test.describe("共用元件預覽", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/dev/ui");
    await expect(page.getByTestId("ui-preview")).toBeVisible();
  });

  test("反灰按鈕：看起來是灰的、有 aria-disabled，點了跳 Toast「暫無作用」", async ({ page }) => {
    for (const id of [
      "placeholder-small",
      "placeholder-button",
      "placeholder-link",
      "placeholder-danger",
    ]) {
      const button = page.getByTestId(id);
      await expect(button).toHaveAttribute("aria-disabled", "true");
      // 不是 HTML 的 disabled（Playwright 的 toBeDisabled 會把 aria-disabled 也算進去，所以直接看屬性），才點得到
      await expect(button).toHaveJSProperty("disabled", false);
      await expect(button).toHaveCSS("opacity", "0.4");
      await button.click({ force: true }); // 略過 Playwright 對 aria-disabled 的可操作性檢查
      await expect(page.getByTestId("toast")).toHaveText("暫無作用");
      await page.getByTestId("toast").waitFor({ state: "hidden", timeout: 5000 });
    }
  });

  test("反灰按鈕可以用鍵盤聚焦並按 Enter", async ({ page }) => {
    const button = page.getByTestId("placeholder-button");
    await button.focus();
    await expect(button).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("toast")).toHaveText("暫無作用");
  });

  test("Toast 一般用法：顯示後自動消失，區域是 role=status", async ({ page }) => {
    await page.getByRole("button", { name: "顯示 Toast" }).click();
    const toast = page.getByRole("status").getByText("已存檔");
    await expect(toast).toBeVisible();
    await expect(toast).toBeHidden({ timeout: 5000 });
  });

  test("按鈕一律白底；主要按鈕是 2px 品牌色框", async ({ page }) => {
    const primary = page.getByRole("button", { name: "主要", exact: true });
    await expect(primary).toHaveCSS("background-color", "rgb(255, 255, 255)");
    await expect(primary).toHaveCSS("border-top-width", "2px");
    await expect(primary).toHaveCSS("border-top-color", "rgb(40, 84, 66)");
    const plain = page.getByRole("button", { name: "預設", exact: true });
    await expect(plain).toHaveCSS("border-top-width", "1px");
    await expect(plain).toHaveCSS("min-height", "48px");
    const stop = page.getByRole("button", { name: "停用", exact: true });
    await expect(stop).toBeDisabled();
  });

  test("提問列：空的時候送出 disabled，有字才啟用，計數即時更新，送出後清空", async ({ page }) => {
    const submit = page.getByTestId("ui-ask-submit");
    await expect(submit).toBeDisabled();
    await page.getByTestId("ui-ask").fill("班機延誤了");
    await expect(page.getByText("5/500")).toBeVisible();
    await expect(submit).toBeEnabled();
    await submit.click();
    await expect(page.getByTestId("ui-ask")).toHaveValue("");
  });

  test("檔案選取：選了檔案顯示「已讀取」", async ({ page }) => {
    await page.getByTestId("ui-file").setInputFiles({
      name: "保單.pdf",
      mimeType: "application/pdf",
      buffer: Buffer.from("%PDF-1.4"),
    });
    await expect(page.getByText("📎 保單.pdf · 已讀取")).toBeVisible();
  });

  test("對話區：我方與 AI 的訊息各自成列，分隔線出現", async ({ page }) => {
    const chat = page.getByTestId("ui-chat");
    await expect(chat.locator("li")).toHaveCount(4);
    await expect(chat.getByText("以下依新的推薦回答")).toBeVisible();
  });

  test("置中對話框：開啟後焦點進入、Esc 關閉", async ({ page }) => {
    await page.getByTestId("open-center").click();
    const dialog = page.getByTestId("ui-dialog-center");
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("heading", { name: "確定寄出？" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
  });

  test("底部抽屜：貼著畫面底部，點選項後關閉", async ({ page }) => {
    await page.getByTestId("open-bottom").click();
    const drawer = page.getByTestId("ui-dialog-bottom");
    await expect(drawer).toBeVisible();
    const box = await drawer.boundingBox();
    const viewport = page.viewportSize();
    expect(box && viewport && Math.abs(box.y + box.height - viewport.height) < 2).toBeTruthy();
    await drawer.getByRole("button", { name: /日本/ }).click();
    await expect(drawer).toBeHidden();
  });

  test("在意事項卡：點選順序、選滿 3 項其餘停用、aria-pressed", async ({ page }) => {
    const cards = page.getByTestId("ui-concerns").getByRole("button");
    await expect(cards.filter({ hasText: "班機延誤" })).toHaveAttribute("aria-pressed", "true");
    await expect(cards.filter({ hasText: "班機延誤" })).toHaveAccessibleName("班機延誤 第 1 順位");
    await expect(cards.filter({ hasText: "行李延誤" })).toBeDisabled();
    await cards.filter({ hasText: "證件遺失" }).click();
    await expect(cards.filter({ hasText: "行李延誤" })).toBeEnabled();
  });

  test("方案卡：改過保額標籤變成「保額（已自行調整）」", async ({ page }) => {
    const alt = page.getByRole("region", { name: "次推薦", exact: true });
    await expect(alt.getByLabel("保額（已自行調整）")).toBeVisible();
    await alt.getByLabel("保額").selectOption({ label: "300 萬（推薦）" });
    await expect(alt.getByLabel("推薦保額")).toBeVisible();
  });

  test("推薦理由卡：展開依據、aria-expanded 切換", async ({ page }) => {
    const toggle = page.getByRole("button", { name: "看推薦依據" });
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await toggle.click();
    await expect(page.getByTestId("basis").getByRole("listitem")).toHaveCount(2);
    await expect(page.getByRole("button", { name: "收合推薦依據" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  test("比較表：你在意的列標「你在意 N」；分頁切換；載入遮罩 role=status", async ({ page }) => {
    await expect(page.getByRole("rowheader", { name: /班機延誤.*你在意 1/ })).toBeVisible();
    await page.getByRole("tab", { name: /行李遺失/ }).click();
    await expect(page.getByText("行李遺失").last()).toBeVisible();
    await page.getByTestId("open-loading").click();
    await expect(page.getByRole("status").filter({ hasText: "正在比較方案…" })).toBeVisible();
  });

  test("手機寬度（390px）下沒有橫向捲動", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 800 });
    await page.goto("/dev/ui");
    await expect(page.getByTestId("ui-preview")).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    );
    expect(overflow).toBe(false);
  });
});
