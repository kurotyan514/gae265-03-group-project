import { expect, type Page, test } from "@playwright/test";
import { setupClaimIncident } from "./helpers";

// 理賠文件上傳的誠實進度（規格 #287、ADR-0027、票 #293）：
// 處理中只有不確定進度；處理完摘要＋預設只列沒通過的，合格的折疊，四個處理階段是輔助資訊。
// 用假 6 號依檔名辨識：「延誤證明」通過、「隨便一份」需要你確認（已先存）、含「缺」不合格、含 bad 讀不出來。
const SLOW = 15_000;
const pdf = (name: string) => ({
  name,
  mimeType: "application/pdf",
  buffer: Buffer.from("%PDF-1.4"),
});

test.beforeEach(async ({ request }) => {
  const config = await (await request.get("/api/v1/auth/config")).json();
  test.skip(!config.dev_login, "後端沒有設 DEV_LOGIN_ENABLED=true");
  test.skip(!(await request.get("/api/v1/plans")).ok(), "條款庫沒有載入，先 make seed");
});

/** 延後上傳回應：每個上傳請求停住，直到 release() 放行（一次放一個，依到達順序） */
async function holdUploads(page: Page) {
  const gates: (() => void)[] = [];
  let sent = 0;
  await page.route("**/api/v1/incidents/*/documents", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    sent++;
    await new Promise<void>((resolve) => gates.push(resolve));
    await route.continue();
  });
  return {
    sent: () => sent,
    release: () => gates.shift()?.(),
  };
}

const rowByName = (page: Page, name: string) =>
  page.getByTestId("upload-row").filter({ hasText: name });

test("處理中：不確定進度、後面的標等待中、依序處理，超過 8 秒追加安撫，回來後才顯示結果", async ({
  page,
}) => {
  const id = await setupClaimIncident(page, "honest-wait");
  await page.clock.install();
  await page.goto(`/incident/${id}`);
  const hold = await holdUploads(page);

  await page.getByTestId("doc-file").setInputFiles([pdf("延誤證明.pdf"), pdf("隨便一份.pdf")]);
  const progress = page.getByTestId("upload-progress");
  await expect(progress).toContainText("正在處理 2 份文件");
  await expect(progress).toContainText("已完成 0／2");
  const first = rowByName(page, "延誤證明");
  const second = rowByName(page, "隨便一份");
  await expect(first.getByTestId("upload-result")).toHaveText("處理中");
  await expect(first).toContainText("小助理正在處理這份文件…");
  await expect(second.getByTestId("upload-result")).toHaveText("等待中");
  await expect(second).not.toContainText("小助理正在處理這份文件…");
  // 沒有逐階段的假動畫，也沒有「讀取內容」
  await expect(page.getByTestId("upload-stages")).toHaveCount(0);
  await expect(progress).not.toContainText("讀取內容");
  // 依序：第一份沒回來，第二份不會送出
  await expect.poll(hold.sent).toBe(1);
  await expect(first.getByTestId("upload-slow")).toHaveCount(0);

  await page.clock.fastForward(8500);
  await expect(first.getByTestId("upload-slow")).toHaveText("照片需要久一點，請稍候");
  await expect(second.getByTestId("upload-slow")).toHaveCount(0);

  hold.release();
  await expect(first.getByTestId("upload-result")).toHaveText("已處理：通過");
  await expect(first.getByTestId("upload-stages")).toBeVisible();
  await expect(progress).toContainText("已完成 1／2");
  await expect(second.getByTestId("upload-result")).toHaveText("處理中");
  await expect.poll(hold.sent).toBe(2);
  // 第二份的安撫從它開始處理才算，不繼承第一份的 8 秒
  await expect(second.getByTestId("upload-slow")).toHaveCount(0);

  hold.release();
  await expect(page.getByTestId("upload-summary")).toContainText("這次上傳 2 份", {
    timeout: SLOW,
  });
});

test("開啟「減少動態」：處理中不轉圈，只顯示文字；處理列是禮貌的即時通知", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  const id = await setupClaimIncident(page, "honest-motion");
  await page.goto(`/incident/${id}`);
  const hold = await holdUploads(page);

  await page.getByTestId("doc-file").setInputFiles(pdf("延誤證明.pdf"));
  await expect(page.getByTestId("upload-working")).toContainText("小助理正在處理這份文件…");
  await expect(page.getByTestId("upload-spinner")).toBeHidden();
  await expect(page.getByTestId("upload-row").locator("xpath=..")).toHaveAttribute(
    "aria-live",
    "polite",
  );
  hold.release();
  await expect(page.getByTestId("upload-summary")).toBeVisible({ timeout: SLOW });
});

test("沒有開「減少動態」時處理中有轉圈", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  const id = await setupClaimIncident(page, "honest-spin");
  await page.goto(`/incident/${id}`);
  const hold = await holdUploads(page);
  await page.getByTestId("doc-file").setInputFiles(pdf("延誤證明.pdf"));
  await expect(page.getByTestId("upload-spinner")).toBeVisible();
  hold.release();
  await expect(page.getByTestId("upload-summary")).toBeVisible({ timeout: SLOW });
});

test("處理完：預設只列沒通過的，合格的折疊；紅字只給不合格，需要你確認是琥珀色", async ({
  page,
}) => {
  const id = await setupClaimIncident(page, "honest-results");
  await page.goto(`/incident/${id}`);
  await page
    .getByTestId("doc-file")
    .setInputFiles([pdf("延誤證明.pdf"), pdf("隨便一份.pdf"), pdf("缺頁證明.pdf"), pdf("bad.pdf")]);
  const summary = page.getByTestId("upload-summary");
  await expect(summary).toContainText("這次上傳 4 份", { timeout: SLOW });
  await expect(summary).toContainText("1 份已自動打勾");
  await expect(summary).toContainText("1 份需要你確認");
  await expect(summary).toContainText("1 份不合格");
  await expect(summary).toContainText("1 份無法辨識");
  await expect(summary).toContainText("看全部 4 份明細");

  // 預設只列 3 份沒通過的
  const rows = page.getByTestId("upload-row");
  await expect(rows).toHaveCount(3);
  await expect(page.getByTestId("upload-result").filter({ hasText: "通過" })).toHaveCount(0);

  const bad = rows.filter({ hasText: "已處理：不合格" });
  await expect(bad.getByTestId("upload-note")).toContainText("停在「檢查內容」");
  await expect(bad.getByTestId("upload-note")).toContainText("這份沒有存到你的 Google Drive");
  await expect(bad.getByTestId("upload-note")).toHaveClass(/text-danger-ink/);
  await expect(bad.getByTestId("upload-result")).toHaveClass(/text-danger-ink/);
  const states = (r: ReturnType<typeof rowByName>) =>
    r
      .getByTestId("upload-stage")
      .evaluateAll((els) => els.map((e) => e.getAttribute("data-state")));
  expect(await states(bad)).toEqual(["ok", "ok", "stop", "nosave"]);

  const unreadable = rows.filter({ hasText: "已處理：讀不出來" });
  await expect(unreadable.getByTestId("upload-note")).toHaveClass(/text-danger-ink/);
  expect(await states(unreadable)).toEqual(["stop", "skip", "skip", "nosave"]);

  // 需要你確認：已先存（待你確認），琥珀色、不是紅字，保留選擇待辦
  const review = rows.filter({ hasText: "需要你確認" });
  await expect(review.getByTestId("upload-result")).toHaveClass(/text-warn-ink/);
  await expect(review.getByTestId("upload-note")).toHaveClass(/text-warn-ink/);
  await expect(review.getByTestId("upload-note")).not.toHaveClass(/text-danger-ink/);
  expect(await states(review)).toEqual(["ok", "stop", "skip", "saved"]);
  await expect(review.getByTestId("upload-stages")).toContainText("存到你的 Google Drive");
  await expect(review.getByTestId("upload-chooser")).toBeVisible();

  // 展開：合格的列出現，綠色標籤、四階段全綠勾、沒有紅字；收合回去
  await page.getByTestId("upload-detail-toggle").click();
  await expect(rows).toHaveCount(4);
  const passed = rows.filter({ hasText: "已處理：通過" });
  await expect(passed.getByTestId("upload-result")).toHaveClass(/text-brand/);
  expect(await states(passed)).toEqual(["ok", "ok", "ok", "ok"]);
  await expect(passed.getByTestId("upload-note")).toHaveCount(0);
  await expect(page.getByTestId("upload-detail-toggle")).toHaveText("收合明細");
  await page.getByTestId("upload-detail-toggle").click();
  await expect(rows).toHaveCount(3);
  await expect(page.getByTestId("upload-detail-toggle")).toHaveText("看全部 4 份明細");
  // 畫面不出現「讀取內容」
  await expect(page.getByTestId("upload-progress")).not.toContainText("讀取內容");
});

test("全部通過：只有摘要與「看全部明細」，不列任何一列", async ({ page }) => {
  const id = await setupClaimIncident(page, "honest-allpass");
  await page.goto(`/incident/${id}`);
  await page.getByTestId("doc-file").setInputFiles(pdf("延誤證明.pdf"));
  await expect(page.getByTestId("upload-summary")).toContainText("這次上傳 1 份", {
    timeout: SLOW,
  });
  await expect(page.getByTestId("upload-row")).toHaveCount(0);
  await expect(page.getByTestId("upload-detail-toggle")).toHaveText("看全部 1 份明細");
});

test("沒有存到 Google Drive：標「沒有完成」、紅字、第 4 階段沒有存，也不能選待辦", async ({
  page,
}) => {
  const id = await setupClaimIncident(page, "honest-nosave");
  await page.goto(`/incident/${id}`);
  // 模擬沒有授權或存檔失敗：6 號回「需要你確認」但沒有檔案（stored=false）
  await page.route("**/api/v1/incidents/*/documents", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({
      response,
      json: { ...body, stored: false, reason: "還沒有 Google 授權" },
    });
  });
  await page.getByTestId("doc-file").setInputFiles(pdf("隨便一份.pdf"));
  await expect(page.getByTestId("upload-summary")).toContainText("這次上傳 1 份", {
    timeout: SLOW,
  });
  const row = page.getByTestId("upload-row");
  await expect(row.getByTestId("upload-result")).toHaveText("沒有完成：沒有存到你的 Google Drive");
  await expect(row.getByTestId("upload-result")).toHaveClass(/text-danger-ink/);
  await expect(row.getByTestId("upload-note")).toHaveClass(/text-danger-ink/);
  await expect(row.getByTestId("upload-note")).toContainText("待辦還沒有勾");
  expect(
    await row
      .getByTestId("upload-stage")
      .evaluateAll((els) => els.map((e) => e.getAttribute("data-state"))),
  ).toEqual(["unknown", "unknown", "unknown", "nosave"]);
  await expect(row.getByTestId("upload-chooser")).toHaveCount(0);
});

test("手機寬度（390px）：處理中與處理完都沒有橫向捲動", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  const id = await setupClaimIncident(page, "honest-mobile");
  await page.goto(`/incident/${id}`);
  const hold = await holdUploads(page);
  const overflow = () =>
    page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    );
  await page.getByTestId("doc-file").setInputFiles([pdf("延誤證明.pdf"), pdf("缺頁證明.pdf")]);
  await expect(page.getByTestId("upload-working")).toBeVisible();
  expect(await overflow()).toBe(false);
  hold.release();
  await expect.poll(hold.sent).toBe(2);
  hold.release();
  await expect(page.getByTestId("upload-summary")).toContainText("這次上傳 2 份", {
    timeout: SLOW,
  });
  await expect(page.getByTestId("upload-stages")).toBeVisible();
  expect(await overflow()).toBe(false);
});
