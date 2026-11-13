import { expect, type Page, test } from "@playwright/test";
import { setupClaimIncident } from "./helpers";

// 理賠文件上傳的預覽（票 #292、規格 #287、ADR-0027）：圖片縮圖可放大，PDF 與 HEIC 是圖示，
// 重新整理後不保留。縮圖與預覽只在瀏覽器；用假 6 號依檔名辨識。
const SLOW = 15_000;
// 1x1 的真 PNG，讓瀏覽器能解碼
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);
const png = (name: string) => ({ name, mimeType: "image/png", buffer: PNG });
const pdf = (name: string) => ({
  name,
  mimeType: "application/pdf",
  buffer: Buffer.from("%PDF-1.4"),
});
/** iPhone 的 HEIC：type 常是空字串 */
const heic = (name: string) => ({ name, mimeType: "", buffer: Buffer.from("heic-bytes") });

test.beforeEach(async ({ request }) => {
  const config = await (await request.get("/api/v1/auth/config")).json();
  test.skip(!config.dev_login, "後端沒有設 DEV_LOGIN_ENABLED=true");
  test.skip(!(await request.get("/api/v1/plans")).ok(), "條款庫沒有載入，先 make seed");
});

/** 延後上傳回應直到 release()，並記錄送出的次數 */
async function holdUploads(page: Page) {
  const gates: (() => void)[] = [];
  let sent = 0;
  await page.route("**/api/v1/incidents/*/documents", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    sent++;
    await new Promise<void>((resolve) => gates.push(resolve));
    await route.continue();
  });
  return { sent: () => sent, release: () => gates.shift()?.() };
}

const rowByName = (page: Page, name: string) =>
  page.getByTestId("upload-row").filter({ hasText: name });
const overflow = (page: Page) =>
  page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);

test("圖片：等待中、處理中、完成後都有縮圖，點縮圖放大，Esc 關閉", async ({ page }) => {
  const id = await setupClaimIncident(page, "preview-image");
  await page.goto(`/incident/${id}`);
  const hold = await holdUploads(page);
  await page.getByTestId("doc-file").setInputFiles([png("延誤證明.png"), png("隨便一份.png")]);

  const first = rowByName(page, "延誤證明");
  const second = rowByName(page, "隨便一份");
  // 處理中與等待中就有縮圖
  await expect(first.getByTestId("upload-result")).toHaveText("讀取內容中…");
  await expect(second.getByTestId("upload-result")).toHaveText("等待中");
  for (const row of [first, second]) {
    const img = row.getByTestId("upload-thumb").locator("img");
    await expect(img).toBeVisible();
    // 真的解碼出圖，而不是破圖
    await expect
      .poll(() => img.evaluate((el: HTMLImageElement) => el.naturalWidth))
      .toBeGreaterThan(0);
    // 縮圖是瀏覽器本機產生的 blob，不是從後端或 Drive 讀的
    await expect(img).toHaveAttribute("src", /^blob:/);
  }
  await expect(first.getByTestId("upload-meta")).toContainText("KB");

  // 點縮圖放大，按鈕有可讀的名稱
  await first.getByRole("button", { name: "放大看 延誤證明.png" }).click();
  const zoom = page.getByTestId("upload-zoom");
  await expect(zoom).toBeVisible();
  await expect(zoom.getByRole("img", { name: "延誤證明.png 放大" })).toBeVisible();
  await expect(zoom).toContainText("延誤證明.png");
  await page.keyboard.press("Escape");
  await expect(zoom).toBeHidden();

  hold.release();
  await expect.poll(hold.sent).toBe(2);
  hold.release();
  await expect(page.getByTestId("upload-summary")).toContainText("這次上傳 2 份", {
    timeout: SLOW,
  });
  // 處理完：沒通過的那份仍有縮圖；合格的折疊，展開後也有縮圖
  await expect(second.getByTestId("upload-thumb")).toBeVisible();
  await expect(first).toHaveCount(0);
  await page.getByTestId("upload-detail-toggle").click();
  await expect(rowByName(page, "延誤證明").getByTestId("upload-thumb")).toBeVisible();
});

test("鍵盤：Tab 到縮圖按 Enter 放大，Esc 關閉並回到縮圖；也能用「關閉」按鈕", async ({ page }) => {
  const id = await setupClaimIncident(page, "preview-keyboard");
  await page.goto(`/incident/${id}`);
  await page.getByTestId("doc-file").setInputFiles([png("隨便一份.png")]);
  await expect(page.getByTestId("upload-summary")).toBeVisible({ timeout: SLOW });
  const thumb = rowByName(page, "隨便一份").getByTestId("upload-thumb");
  await thumb.focus();
  await page.keyboard.press("Enter");
  const zoom = page.getByTestId("upload-zoom");
  await expect(zoom).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(zoom).toBeHidden();
  await expect(thumb).toBeFocused();

  await thumb.click();
  await expect(zoom).toBeVisible();
  await page.getByTestId("upload-zoom-close").click();
  await expect(zoom).toBeHidden();
});

test("PDF 顯示圖示、檔名與大小；HEIC 顯示「無法預覽，但仍會上傳」且照常送出", async ({ page }) => {
  const id = await setupClaimIncident(page, "preview-icons");
  await page.goto(`/incident/${id}`);
  const hold = await holdUploads(page);
  await page.getByTestId("doc-file").setInputFiles([pdf("延誤證明.pdf"), heic("IMG_0001.HEIC")]);

  const pdfRow = rowByName(page, "延誤證明.pdf");
  await expect(pdfRow.getByTestId("upload-icon")).toHaveAttribute("data-kind", "pdf");
  await expect(pdfRow.getByTestId("upload-icon")).toHaveText("PDF");
  await expect(pdfRow.getByTestId("upload-thumb")).toHaveCount(0);
  await expect(pdfRow.getByTestId("upload-meta")).toContainText("KB");
  await expect(pdfRow.getByTestId("upload-heic-note")).toHaveCount(0);

  const heicRow = rowByName(page, "IMG_0001.HEIC");
  await expect(heicRow.getByTestId("upload-icon")).toHaveAttribute("data-kind", "heic");
  await expect(heicRow.getByTestId("upload-thumb")).toHaveCount(0);
  await expect(heicRow.getByTestId("upload-heic-note")).toContainText("無法預覽，但仍會上傳");

  // 兩份都照常送出（HEIC 不被前端擋下）
  hold.release();
  await expect.poll(hold.sent).toBe(2);
  hold.release();
  await expect(page.getByTestId("upload-summary")).toContainText("這次上傳 2 份", {
    timeout: SLOW,
  });
});

test("新一批開始與離開頁面時釋放預覽（revokeObjectURL）", async ({ page }) => {
  await page.addInitScript(() => {
    const w = window as unknown as { __revoked: string[] };
    w.__revoked = [];
    const orig = URL.revokeObjectURL.bind(URL);
    URL.revokeObjectURL = (u: string) => {
      w.__revoked.push(u);
      orig(u);
    };
  });
  const id = await setupClaimIncident(page, "preview-revoke");
  await page.goto(`/incident/${id}`);
  await page.getByTestId("doc-file").setInputFiles([png("隨便一份.png")]);
  await expect(page.getByTestId("upload-summary")).toBeVisible({ timeout: SLOW });
  const url = await rowByName(page, "隨便一份")
    .getByTestId("upload-thumb")
    .locator("img")
    .getAttribute("src");
  const revoked = () => page.evaluate(() => (window as never as { __revoked: string[] }).__revoked);
  expect(await revoked()).not.toContain(url);

  // 新一批開始：前一批的縮圖網址被釋放
  await page.getByTestId("doc-file").setInputFiles([png("另一份.png")]);
  await expect.poll(revoked).toContain(url);
  await expect(page.getByTestId("upload-summary")).toBeVisible({ timeout: SLOW });

  // 離開頁面（元件卸載）：這一批也被釋放
  const url2 = await rowByName(page, "另一份")
    .getByTestId("upload-thumb")
    .locator("img")
    .getAttribute("src");
  await page.locator("header a, nav a").first().click();
  await expect.poll(revoked).toContain(url2);
});

test("重新整理後縮圖不保留，也不從 Drive 讀回", async ({ page }) => {
  const id = await setupClaimIncident(page, "preview-reload");
  await page.goto(`/incident/${id}`);
  await page.getByTestId("doc-file").setInputFiles([png("延誤證明.png")]);
  await expect(page.getByTestId("upload-summary")).toBeVisible({ timeout: SLOW });
  await page.getByTestId("upload-detail-toggle").click();
  await expect(page.getByTestId("upload-thumb")).toBeVisible();

  const driveReads: string[] = [];
  page.on("request", (r) => {
    if (/drive\.google|googleusercontent|thumbnail/i.test(r.url())) driveReads.push(r.url());
  });
  await page.reload();
  await expect(page.getByTestId("upload-box")).toBeVisible();
  await expect(page.getByTestId("upload-thumb")).toHaveCount(0);
  await expect(page.getByTestId("upload-icon")).toHaveCount(0);
  await expect(page.getByTestId("upload-row")).toHaveCount(0);
  expect(driveReads).toEqual([]);
});

test("手機寬度（390px）：縮圖與清單不橫向捲動，放大的圖可以關閉", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  const id = await setupClaimIncident(page, "preview-mobile");
  await page.goto(`/incident/${id}`);
  const hold = await holdUploads(page);
  await page
    .getByTestId("doc-file")
    .setInputFiles([
      png("一個很長很長很長很長很長很長很長很長很長很長的檔名.png"),
      pdf("延誤證明.pdf"),
      heic("IMG_0002.heic"),
    ]);
  await expect(page.getByTestId("upload-thumb")).toBeVisible();
  expect(await overflow(page)).toBe(false);

  await page.getByTestId("upload-thumb").click();
  const zoom = page.getByTestId("upload-zoom");
  await expect(zoom).toBeVisible();
  const box = await zoom.boundingBox();
  expect(box && box.x >= 0 && box.x + box.width <= 390).toBe(true);
  expect(await overflow(page)).toBe(false);
  await page.getByTestId("upload-zoom-close").click();
  await expect(zoom).toBeHidden();

  for (let i = 0; i < 3; i++) {
    await expect.poll(hold.sent).toBe(i + 1);
    hold.release();
  }
  await expect(page.getByTestId("upload-summary")).toBeVisible({ timeout: SLOW });
  expect(await overflow(page)).toBe(false);
});
