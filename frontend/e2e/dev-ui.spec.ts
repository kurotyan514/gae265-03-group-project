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

// 處理清單原型（#290、規格 #287）：靜態示意，涵蓋票上所有狀態
test.describe("處理清單原型", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/dev/ui");
    await expect(page.getByTestId("pp-root")).toBeVisible();
  });

  test("處理中：只有一句不確定進度，排在後面的標等待中，沒有逐階段動畫", async ({ page }) => {
    const batch = page.getByTestId("pp-batch");
    await expect(batch.getByText("小助理正在處理這份文件…")).toHaveCount(1);
    await expect(batch.getByTestId("pp-badge")).toHaveText(["處理中", "等待中", "等待中"]);
    await expect(batch.getByText("已完成 0／3")).toBeVisible();
    // 等待中沒有任何階段名稱
    await expect(batch.getByTestId("pp-stages")).toHaveCount(0);
    await expect(batch.getByText("存到你的 Google Drive")).toHaveCount(0);
    await expect(batch.getByTestId("pp-slow")).toHaveCount(0);
  });

  test("超過 8 秒追加安撫文字", async ({ page }) => {
    await expect(page.getByTestId("pp-slow-frame").getByTestId("pp-slow")).toHaveText(
      "照片需要久一點，請稍候",
    );
  });

  test("預覽：圖片是縮圖、PDF 與 HEIC 是圖示加檔名與大小，HEIC 說明仍會上傳", async ({ page }) => {
    const rows = page.getByTestId("pp-batch").getByTestId("pp-row");
    await expect(rows.nth(0).getByTestId("pp-thumb")).toBeVisible();
    await expect(rows.nth(1).getByTestId("pp-icon")).toHaveText("PDF");
    await expect(rows.nth(1)).toContainText("登機證.pdf");
    await expect(rows.nth(1)).toContainText("186 KB");
    await expect(rows.nth(2).getByTestId("pp-icon")).toHaveText("HEIC");
    await expect(rows.nth(2).getByTestId("pp-heic-note")).toContainText("無法預覽，但仍會上傳");
  });

  test("縮圖可以點開放大，Esc 關閉，鍵盤也能開", async ({ page }) => {
    const thumb = page.getByTestId("pp-batch").getByTestId("pp-thumb");
    await thumb.click();
    await expect(page.getByTestId("pp-zoom")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("pp-zoom")).toBeHidden();
    await thumb.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("pp-zoom")).toBeVisible();
    await page.getByTestId("pp-zoom-close").click();
    await expect(page.getByTestId("pp-zoom")).toBeHidden();
  });

  test("處理完：摘要加看全部明細，預設只列沒通過的，合格的折疊", async ({ page }) => {
    const list = page.getByTestId("pp-list-mixed");
    await expect(list).toContainText("這次上傳 9 份：");
    await expect(page.getByTestId("pp-summary").first()).toContainText("1 份已自動打勾");
    await expect(page.getByTestId("pp-summary").first()).toContainText("2 份沒有完成");
    const rows = list.getByTestId("pp-res-row");
    await expect(rows).toHaveCount(6);
    // 合格的（通過、還缺另一份、追加）預設看不到
    for (const name of ["延誤證明.jpg", "登機證.jpg", "診斷證明-第二頁.jpg"]) {
      await expect(list.getByText(name)).toHaveCount(0);
    }
    await expect(list.getByTestId("pp-toggle")).toHaveText("看全部 9 份明細");
    await expect(list.getByTestId("pp-toggle")).toHaveAttribute("aria-expanded", "false");
  });

  test("看全部明細展開、收合", async ({ page }) => {
    const list = page.getByTestId("pp-list-mixed");
    await list.getByTestId("pp-toggle").click();
    await expect(list.getByTestId("pp-res-row")).toHaveCount(9);
    await expect(list.getByTestId("pp-toggle")).toHaveText("收合明細");
    await expect(list.getByText("延誤證明.jpg")).toBeVisible();
    // 合格的列：綠色標籤，階段是全部綠勾的緊湊一行
    const pass = list.getByTestId("pp-res-row").filter({ hasText: "延誤證明.jpg" });
    await expect(pass.getByTestId("pp-badge")).toHaveClass(/text-brand/);
    await expect(pass.getByTestId("pp-stage")).toHaveCount(4);
    await expect(pass.getByTestId("pp-stage").locator("i.bg-leaf")).toHaveCount(4);
    await list.getByTestId("pp-toggle").click();
    await expect(list.getByTestId("pp-res-row")).toHaveCount(6);
    await expect(list.getByTestId("pp-toggle")).toHaveText("看全部 9 份明細");
  });

  test("紅字只給不合格的列；需要你確認是琥珀色；合格的列沒有紅字", async ({ page }) => {
    const list = page.getByTestId("pp-list-mixed");
    const red = (name: string) =>
      list.getByTestId("pp-res-row").filter({ hasText: name }).locator(".text-danger-ink");
    for (const name of [
      "診斷證明.pdf",
      "行李證明.jpg",
      "班機延誤證明.pdf",
      "模糊的照片.jpg",
      "IMG_0420.HEIC",
    ]) {
      await expect(red(name).first()).toBeVisible();
    }
    const review = list.getByTestId("pp-res-row").filter({ hasText: "收據.jpg" });
    await expect(review.getByTestId("pp-badge")).toHaveText("需要你確認");
    await expect(review.getByTestId("pp-badge")).toHaveClass(/text-warn-ink/);
    await expect(review.locator(".text-danger-ink")).toHaveCount(0);
    // 需要你確認：已先存到 Drive，不是「沒有存」
    await expect(review).toContainText("已先存到你的 Google Drive，等你確認後才算正式");
    // 合格的列（展開後）沒有紅字
    await list.getByTestId("pp-toggle").click();
    for (const name of ["延誤證明.jpg", "登機證.jpg", "診斷證明-第二頁.jpg"]) {
      await expect(red(name)).toHaveCount(0);
    }
  });

  test("沒有完成：標籤不含通過，說明沒有存、待辦沒勾與下一步；停下的那一步紅色", async ({
    page,
  }) => {
    const list = page.getByTestId("pp-list-mixed");
    for (const name of ["行李證明.jpg", "班機延誤證明.pdf"]) {
      const row = list.getByTestId("pp-res-row").filter({ hasText: name });
      await expect(row.getByTestId("pp-badge")).toHaveText("沒有完成：沒有存到你的 Google Drive");
      await expect(row.getByTestId("pp-reason")).toContainText("待辦還沒有勾");
      await expect(row.getByTestId("pp-reason")).toContainText("下一步");
    }
    await expect(list.getByTestId("pp-authorize")).toBeVisible();
    // 不合格：只有停下與沒有存的那一步是紅色
    const bad = list.getByTestId("pp-res-row").filter({ hasText: "診斷證明.pdf" });
    await expect(bad.getByTestId("pp-stage").locator("i.bg-coral")).toHaveCount(2);
    await expect(bad.getByTestId("pp-reason")).toContainText("缺少就診日期");
    // 契約不可能出現「通過但沒有存」
    await expect(page.getByTestId("pp-root")).not.toContainText("通過，但沒有存");
  });

  test("全部合格時只有摘要與看全部明細", async ({ page }) => {
    const list = page.getByTestId("pp-list-pass");
    await expect(list).toContainText("這次上傳 2 份：");
    await expect(list.getByTestId("pp-summary")).toHaveText("2 份已自動打勾");
    await expect(list.getByTestId("pp-res-row")).toHaveCount(0);
    await list.getByTestId("pp-toggle").click();
    await expect(list.getByTestId("pp-res-row")).toHaveCount(2);
    await expect(list.getByTestId("pp-toggle")).toHaveText("收合明細");
  });

  test("手機寬度：展開後仍沒有橫向捲動", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByTestId("pp-list-mixed").getByTestId("pp-toggle").click();
    await page.getByTestId("pp-list-pass").getByTestId("pp-toggle").click();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });

  test("網路中斷：說明可能已處理好，不叫人重傳", async ({ page }) => {
    const offline = page.getByTestId("pp-offline");
    await expect(offline).toContainText("連線中斷，這份文件可能已經處理好了");
    await expect(offline).toContainText("請先不要重傳");
  });

  test("給旅客看的文案用小助理，不出現 agent、辨識、OCR，也不顯示階段輸入輸出", async ({
    page,
  }) => {
    await page.getByTestId("pp-batch").getByTestId("pp-thumb").click();
    const aria = await page
      .getByTestId("pp-root")
      .locator("[aria-label]")
      .evaluateAll((els) => els.map((e) => e.getAttribute("aria-label")).join(" "));
    const zoomText = (await page.getByTestId("pp-zoom").textContent()) ?? "";
    const text = `${(await page.getByTestId("pp-root").textContent()) ?? ""} ${aria} ${zoomText}`;
    expect(text).toContain("小助理");
    expect(text).not.toMatch(/agent|辨識|OCR/i);
    expect(text).not.toMatch(/輸入：|輸出：/);
  });

  test("減少動態：不轉圈，只顯示文字", async ({ page }) => {
    await expect(page.getByTestId("pp-batch").getByTestId("pp-spinner")).toBeVisible();
    // 預覽頁直接展示的「減少動態」樣子：沒有轉圈元素
    await expect(page.getByTestId("pp-reduced").getByTestId("pp-spinner")).toHaveCount(0);
    await expect(page.getByTestId("pp-reduced").getByText("小助理正在處理這份文件…")).toBeVisible();
    // 系統設定減少動態時，其餘的轉圈也隱藏
    await page.emulateMedia({ reducedMotion: "reduce" });
    await expect(page.getByTestId("pp-batch").getByTestId("pp-spinner")).toBeHidden();
    await expect(page.getByTestId("pp-batch").getByText("小助理正在處理這份文件…")).toBeVisible();
  });

  test("390px 沒有橫向捲動", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
    // 原型本身也不能超出自己的欄寬
    const box = await page.getByTestId("pp-root").boundingBox();
    expect(box?.width ?? 999).toBeLessThanOrEqual(390);
  });
});
