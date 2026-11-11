import { expect, type Page, test } from "@playwright/test";
import { setupClaimIncident } from "./helpers";

// 理賠文件上傳的網路中斷與錯誤（規格 #287、ADR-0027、票 #294）：
// 連線中斷時不叫旅客盲目重傳（重新讀取事件判斷有沒有進去）；太大、不支援的檔案有明確原因；不設前端逾時。
// 用假 6 號依檔名辨識：「延誤證明」通過。
const SLOW = 20_000;
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

const uploadUrl = "**/api/v1/incidents/*/documents";

/** 記下送出的上傳請求次數（GET 不算） */
async function countUploads(page: Page) {
  let sent = 0;
  await page.route(uploadUrl, async (route) => {
    if (route.request().method() === "POST") sent++;
    await route.continue();
  });
  return () => sent;
}

test("連線中斷但伺服器已處理好：自動重新讀取，標為已處理，說明不用重傳", async ({ page }) => {
  const id = await setupClaimIncident(page, "err-landed");
  await page.goto(`/incident/${id}`);
  let reads = 0;
  page.on("request", (r) => {
    if (r.method() === "GET" && r.url().endsWith(`/api/v1/incidents/${id}`)) reads++;
  });
  // 伺服器照常處理完，但回應到不了瀏覽器
  await page.route(uploadUrl, async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    await route.fetch();
    await route.abort("connectionreset");
  });
  const readsBefore = reads;
  await page.getByTestId("doc-file").setInputFiles(pdf("延誤證明.pdf"));
  const summary = page.getByTestId("upload-summary");
  await expect(summary).toContainText("這次上傳 1 份", { timeout: SLOW });
  expect(reads).toBeGreaterThan(readsBefore);
  await expect(summary).toContainText("1 份已自動打勾");
  // 這份不折疊：旅客要看到發生過什麼
  const row = page.getByTestId("upload-row");
  await expect(row).toHaveCount(1);
  await expect(row.getByTestId("upload-result")).toHaveText("符合規則，已自動打勾");
  await expect(row.getByTestId("upload-note")).toContainText("連線中斷時，伺服器已經處理好這份");
  await expect(row.getByTestId("upload-note")).toContainText("不用重傳");
  await expect(page.getByTestId("upload-reconnecting")).toHaveCount(0);
});

test("連線中斷且沒有收到：說明可能處理好了、確認中不是「處理中」，最後提示可以重傳", async ({
  page,
}) => {
  const id = await setupClaimIncident(page, "err-lost");
  await page.goto(`/incident/${id}`);
  // 請求根本沒到伺服器
  await page.route(uploadUrl, async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    await route.abort("connectionreset");
  });
  await page.getByTestId("doc-file").setInputFiles(pdf("延誤證明.pdf"));
  const reconnecting = page.getByTestId("upload-reconnecting");
  await expect(reconnecting).toHaveText("連線中斷，這份文件可能已經處理好了，正在確認…");
  await expect(page.getByTestId("upload-working")).toHaveCount(0);

  const summary = page.getByTestId("upload-summary");
  await expect(summary).toContainText("1 份上傳失敗", { timeout: SLOW });
  const row = page.getByTestId("upload-row");
  await expect(row.getByTestId("upload-result")).toHaveText("上傳失敗");
  await expect(row).toContainText("連線中斷，還沒有看到這份文件的處理結果");
  await expect(row).toContainText("可以再傳一次");
  await expect(page.getByTestId("doc-file")).toBeEnabled();
});

test("超過 10 MB：直接說明原因，不送出、不顯示成處理中", async ({ page }) => {
  const id = await setupClaimIncident(page, "err-big");
  await page.goto(`/incident/${id}`);
  const sent = await countUploads(page);
  await page.getByTestId("doc-file").setInputFiles({
    name: "延誤證明.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.alloc(10 * 1024 * 1024 + 1),
  });
  const summary = page.getByTestId("upload-summary");
  await expect(summary).toContainText("1 份上傳失敗", { timeout: SLOW });
  await expect(page.getByTestId("upload-row")).toContainText("檔案超過 10 MB");
  await expect(page.getByTestId("upload-working")).toHaveCount(0);
  expect(sent()).toBe(0);
});

test("不支援的檔案類型：直接說明原因，不送出；同一批的其他檔案照常處理", async ({ page }) => {
  const id = await setupClaimIncident(page, "err-type");
  await page.goto(`/incident/${id}`);
  const sent = await countUploads(page);
  await page
    .getByTestId("doc-file")
    .setInputFiles([
      { name: "說明.txt", mimeType: "text/plain", buffer: Buffer.from("hello") },
      pdf("延誤證明.pdf"),
    ]);
  const summary = page.getByTestId("upload-summary");
  await expect(summary).toContainText("這次上傳 2 份", { timeout: SLOW });
  await expect(summary).toContainText("1 份已自動打勾");
  await expect(summary).toContainText("1 份上傳失敗");
  const bad = page.getByTestId("upload-row").filter({ hasText: "說明.txt" });
  await expect(bad).toContainText("這個檔案類型不支援");
  await expect(bad).toContainText("PDF、JPG 或 PNG");
  expect(sent()).toBe(1);
});

test("伺服器回 413（太大）：顯示伺服器給的原因", async ({ page }) => {
  const id = await setupClaimIncident(page, "err-413");
  await page.goto(`/incident/${id}`);
  await page.route(uploadUrl, async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    await route.fulfill({ status: 413, json: { detail: "檔案超過 10 MB" } });
  });
  await page.getByTestId("doc-file").setInputFiles(pdf("延誤證明.pdf"));
  await expect(page.getByTestId("upload-row")).toContainText("檔案超過 10 MB", { timeout: SLOW });
  await expect(page.getByTestId("upload-result")).toHaveText("上傳失敗");
});

test("不設前端逾時：處理很久也不會被畫面自己打斷", async ({ page }) => {
  const id = await setupClaimIncident(page, "err-noabort");
  await page.clock.install();
  await page.goto(`/incident/${id}`);
  const gates: (() => void)[] = [];
  await page.route(uploadUrl, async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    await new Promise<void>((resolve) => gates.push(resolve));
    await route.continue();
  });
  await page.getByTestId("doc-file").setInputFiles(pdf("延誤證明.pdf"));
  await expect(page.getByTestId("upload-working")).toBeVisible();
  // 三分鐘過去，仍在處理中，沒有錯誤、也沒有「連線中斷」
  await page.clock.fastForward(180_000);
  await expect(page.getByTestId("upload-working")).toBeVisible();
  await expect(page.getByTestId("upload-reconnecting")).toHaveCount(0);
  await expect(page.getByTestId("upload-row")).not.toContainText("上傳失敗");
  gates.shift()?.();
  await expect(page.getByTestId("upload-summary")).toContainText("1 份已自動打勾", {
    timeout: SLOW,
  });
});
