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

/**
 * 主題色的實際 rgb（把 CSS 變數放到探針元素上解析），讓測試驗顏色而不是 class 名稱。
 * token 不存在（例如被 Tailwind 修剪）時，探針會悄悄繼承 body 的顏色，所以要求結果不等於 body 顏色。
 */
async function themeColor(page: Page, name: string) {
  const { rgb, inherited } = await page.evaluate((n) => {
    const probe = document.createElement("i");
    probe.style.color = `var(--color-${n})`;
    document.body.append(probe);
    const rgb = getComputedStyle(probe).color;
    probe.remove();
    return { rgb, inherited: rgb === getComputedStyle(document.body).color };
  }, name);
  expect(inherited, `--color-${name} 沒有解析成顏色（探針繼承了 body 的顏色）`).toBe(false);
  return rgb;
}

const rowByName = (page: Page, name: string) =>
  page.getByTestId("upload-row").filter({ hasText: name });

test("處理中：顯示三個步驟、後面的標等待中、依序處理，超過 8 秒追加安撫，回來後才顯示結果", async ({
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
  // 三個步驟（1113 討論、ADR-0028）：回應回來之前停在「讀取內容」
  await expect(first.getByTestId("upload-result")).toHaveText("讀取內容中…");
  const steps = first.getByTestId("upload-step");
  await expect(steps).toHaveText(["讀取內容", "對應待辦", "檢查規則"]);
  await expect(steps.nth(0)).toHaveAttribute("data-state", "run");
  await expect(steps.nth(1)).toHaveAttribute("data-state", "wait");
  await expect(second.getByTestId("upload-result")).toHaveText("等待中");
  await expect(second.getByTestId("upload-steps")).toHaveCount(0);
  // 「小助理正在處理這份文件…」不再使用
  await expect(progress).not.toContainText("小助理正在處理");
  // 依序：第一份沒回來，第二份不會送出
  await expect.poll(hold.sent).toBe(1);
  await expect(first.getByTestId("upload-slow")).toHaveCount(0);

  await page.clock.fastForward(8500);
  await expect(first.getByTestId("upload-slow")).toHaveText("照片需要久一點，請稍候");
  await expect(second.getByTestId("upload-slow")).toHaveCount(0);

  hold.release();
  await expect(first.getByTestId("upload-result")).toHaveText("符合規則，已自動打勾");
  // 有結果後步驟收起，只留結果
  await expect(first.getByTestId("upload-steps")).toHaveCount(0);
  await expect(progress).toContainText("已完成 1／2");
  await expect(second.getByTestId("upload-result")).toHaveText("讀取內容中…");
  await expect.poll(hold.sent).toBe(2);
  // 第二份的安撫從它開始處理才算，不繼承第一份的 8 秒
  await expect(second.getByTestId("upload-slow")).toHaveCount(0);

  hold.release();
  await expect(page.getByTestId("upload-summary")).toContainText("這次上傳 2 份", {
    timeout: SLOW,
  });
});

/** 正在做的那一步的圓圈有沒有在轉 */
const spinning = (page: Page) =>
  page
    .locator('[data-testid="upload-step"][data-state="run"] i')
    .evaluate((el) => getComputedStyle(el).animationName !== "none");

test("開啟「減少動態」：處理中的步驟不轉圈", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  const id = await setupClaimIncident(page, "honest-motion");
  await page.goto(`/incident/${id}`);
  const hold = await holdUploads(page);

  await page.getByTestId("doc-file").setInputFiles(pdf("延誤證明.pdf"));
  await expect(page.getByTestId("upload-steps")).toContainText("讀取內容");
  expect(await spinning(page)).toBe(false);
  hold.release();
  await expect(page.getByTestId("upload-summary")).toBeVisible({ timeout: SLOW });
});

test("沒有開「減少動態」時正在做的那一步有轉圈", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  const id = await setupClaimIncident(page, "honest-spin");
  await page.goto(`/incident/${id}`);
  const hold = await holdUploads(page);
  await page.getByTestId("doc-file").setInputFiles(pdf("延誤證明.pdf"));
  await expect(page.getByTestId("upload-steps")).toBeVisible();
  expect(await spinning(page)).toBe(true);
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
  await expect(page.getByTestId("upload-result").filter({ hasText: "符合規則" })).toHaveCount(0);

  const red = await themeColor(page, "danger-ink");
  const amber = await themeColor(page, "warn-ink");
  const green = await themeColor(page, "brand");
  // 不合格：紅字（標籤、原因），標籤帶缺少什麼與檔案未保留；說明只有 6 號的原因與下一步（1113 討論）
  const bad = rows.filter({ hasText: "不合格" });
  await expect(bad.getByTestId("upload-result")).toHaveText(/^不合格.*（檔案未保留）$/);
  // 6 號寫的原因要保留（假 6 號：缺少最後一頁）
  await expect(bad.getByTestId("upload-note")).toContainText("缺少最後一頁");
  await expect(bad.getByTestId("upload-note")).not.toContainText("停在");
  await expect(bad.getByTestId("upload-note")).not.toContainText("Google Drive");
  await expect(bad.getByTestId("upload-result")).toHaveCSS("color", red);
  await expect(bad.getByTestId("upload-note")).toHaveCSS("color", red);

  const unreadable = rows.filter({ hasText: "無法辨識（檔案未保留）" });
  await expect(unreadable.getByTestId("upload-result")).toHaveCSS("color", red);
  await expect(unreadable.getByTestId("upload-note")).toHaveCSS("color", red);

  // 需要你確認：琥珀色、沒有紅色，保留選擇待辦；不再寫「已先存到你的 Google Drive」
  const review = rows.filter({ hasText: "需要你確認" });
  await expect(review.getByTestId("upload-result")).toHaveCSS("color", amber);
  await expect(review.getByTestId("upload-note")).toHaveCSS("color", amber);
  await expect(review.getByTestId("upload-note")).not.toContainText("Google Drive");
  // 顯示 6 號給的原因，不是固定句子（假 6 號：無法判斷文件類型，請人工確認）
  await expect(review.getByTestId("upload-note")).toContainText("無法判斷文件類型，請人工確認");
  await expect(review.getByTestId("upload-chooser")).toBeVisible();

  // 展開：合格的列出現，綠色標籤、判斷依據、沒有紅字；按鈕與列表用 aria-controls 相連；收合回去
  const toggle = page.getByTestId("upload-detail-toggle");
  const listId = await toggle.getAttribute("aria-controls");
  expect(listId).toBeTruthy();
  await expect(page.locator(`ul[id="${listId}"]`)).toBeVisible();
  await toggle.click();
  await expect(rows).toHaveCount(4);
  const passed = rows.filter({ hasText: "符合規則，已自動打勾" });
  await expect(passed.getByTestId("upload-result")).toHaveCSS("color", green);
  await expect(passed.getByTestId("upload-note")).toHaveCount(0);
  await expect(passed.getByTestId("upload-basis")).toContainText("對應：");
  await expect(toggle).toHaveText("收合明細");
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await toggle.click();
  await expect(rows).toHaveCount(3);
  await expect(toggle).toHaveText("看全部 4 份明細");
  // 處理完不顯示步驟，也沒有「停在〇〇」；檔案有沒有保留看標籤上的「（檔案未保留）」
  await expect(page.getByTestId("upload-steps")).toHaveCount(0);
  await expect(page.getByTestId("upload-progress")).not.toContainText("停在");
  // 即時通知整批處理完念一次摘要（含被折疊的合格列），不是只念最後一份
  const announce = page.getByTestId("upload-announce");
  await expect(announce).toHaveAttribute("role", "status");
  await expect(announce).toContainText("上傳完成，共 4 份");
  await expect(announce).toContainText("1 份已自動打勾");
  await expect(announce).toContainText("1 份需要你確認");
  await expect(announce).toContainText("1 份不合格");
  await expect(announce).toContainText("1 份無法辨識");
  await expect(page.getByTestId("upload-progress")).not.toContainText("讀取內容");
});

test("通過但附提醒：不折疊，預設列出，琥珀色、提醒文字可見；合格的折疊但結果仍會通知讀屏", async ({
  page,
}) => {
  const id = await setupClaimIncident(page, "honest-remind");
  await page.goto(`/incident/${id}`);
  await page.route("**/api/v1/incidents/*/documents", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({
      response,
      json: { ...body, reason: "證明上沒看到延誤原因，建議向航空公司索取註明原因的證明" },
    });
  });
  await page.getByTestId("doc-file").setInputFiles(pdf("延誤證明.pdf"));
  await expect(page.getByTestId("upload-summary")).toContainText(
    "1 份已自動打勾（其中 1 份有提醒）",
    { timeout: SLOW },
  );
  const row = page.getByTestId("upload-row");
  await expect(row).toHaveCount(1);
  await expect(row.getByTestId("upload-result")).toHaveText("符合規則，已自動打勾（有提醒）");
  await expect(row.getByTestId("upload-note")).toContainText("提醒：證明上沒看到延誤原因");
  const amber = await themeColor(page, "warn-ink");
  await expect(row.getByTestId("upload-result")).toHaveCSS("color", amber);
  await expect(row.getByTestId("upload-note")).toHaveCSS("color", amber);
  await expect(page.getByTestId("upload-announce")).toContainText(
    "1 份已自動打勾（其中 1 份有提醒）",
  );
});

test("合格的列折疊時，讀屏的即時通知仍念出結果摘要", async ({ page }) => {
  const id = await setupClaimIncident(page, "honest-announce");
  await page.goto(`/incident/${id}`);
  await page.getByTestId("doc-file").setInputFiles(pdf("延誤證明.pdf"));
  await expect(page.getByTestId("upload-summary")).toBeVisible({ timeout: SLOW });
  await expect(page.getByTestId("upload-row")).toHaveCount(0);
  await expect(page.getByTestId("upload-announce")).toContainText("上傳完成，共 1 份");
  await expect(page.getByTestId("upload-announce")).toContainText("1 份已自動打勾");
  await expect(page.getByTestId("upload-announce")).toHaveAttribute("role", "status");
});

test("追加到已完成的待辦：合格，預設折疊；摘要與讀屏通知有份數，展開後有判斷依據", async ({
  page,
}) => {
  const id = await setupClaimIncident(page, "honest-appended");
  await page.goto(`/incident/${id}`);
  // 模擬這項待辦先前已完成、這份是追加的（6 號回 appended）
  await page.route("**/api/v1/incidents/*/documents", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({ response, json: { ...body, appended: true } });
  });
  await page.getByTestId("doc-file").setInputFiles(pdf("延誤證明.pdf"));
  const summary = page.getByTestId("upload-summary");
  await expect(summary).toContainText("1 份追加到已完成的待辦", { timeout: SLOW });
  await expect(page.getByTestId("upload-announce")).toContainText("1 份追加到已完成的待辦");
  await expect(page.getByTestId("upload-row")).toHaveCount(0);
  await page.getByTestId("upload-detail-toggle").click();
  const row = page.getByTestId("upload-row");
  await expect(row.getByTestId("upload-result")).toHaveText("已追加到已完成的待辦");
  await expect(row.getByTestId("upload-basis")).toContainText("追加為新的一份");
});

/** 讓上傳回應多帶欄位：模擬 6 號回「追加」「還缺另一份」與提醒（假 6 號只會回通過） */
async function mockUploadResponse(page: Page, patch: Record<string, unknown>) {
  await page.route("**/api/v1/incidents/*/documents", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({ response, json: { ...body, ...patch } });
  });
}

test("追加到已完成的待辦帶提醒：不折疊、琥珀色、預設列出，摘要算進「有提醒」（票 #305）", async ({
  page,
}) => {
  const id = await setupClaimIncident(page, "honest-appended-remind");
  await page.goto(`/incident/${id}`);
  await mockUploadResponse(page, { appended: true, reason: "這張登機證的日期與行程不同，請確認" });
  await page.getByTestId("doc-file").setInputFiles(pdf("延誤證明.pdf"));
  const summary = page.getByTestId("upload-summary");
  await expect(summary).toContainText("1 份追加到已完成的待辦（其中 1 份有提醒）", {
    timeout: SLOW,
  });
  await expect(summary).not.toContainText("已自動打勾（其中");
  await expect(page.getByTestId("upload-announce")).toContainText(
    "1 份追加到已完成的待辦（其中 1 份有提醒）",
  );
  const row = page.getByTestId("upload-row");
  await expect(row).toHaveCount(1);
  await expect(row.getByTestId("upload-result")).toHaveText("已追加到已完成的待辦（有提醒）");
  await expect(row.getByTestId("upload-note")).toContainText("提醒：這張登機證的日期與行程不同");
  const amber = await themeColor(page, "warn-ink");
  await expect(row.getByTestId("upload-result")).toHaveCSS("color", amber);
  await expect(row.getByTestId("upload-note")).toHaveCSS("color", amber);
});

test("還缺另一份帶提醒：不折疊，標籤是缺什麼，提醒只列提醒、不重複缺的說明（票 #305）", async ({
  page,
}) => {
  const id = await setupClaimIncident(page, "honest-lack-remind");
  await page.goto(`/incident/${id}`);
  await mockUploadResponse(page, {
    todo_complete: false,
    reason: "已收到，還缺登機證（或改傳一份搭機證明）；證明上沒看到延誤原因，建議向航空公司索取",
  });
  await page.getByTestId("doc-file").setInputFiles(pdf("延誤證明.pdf"));
  const summary = page.getByTestId("upload-summary");
  await expect(summary).toContainText("1 份已收到、還缺其他文件（其中 1 份有提醒）", {
    timeout: SLOW,
  });
  const row = page.getByTestId("upload-row");
  await expect(row).toHaveCount(1);
  await expect(row.getByTestId("upload-result")).toHaveText("符合規則，還缺登機證（有提醒）");
  const note = row.getByTestId("upload-note");
  await expect(note).toHaveText("提醒：證明上沒看到延誤原因，建議向航空公司索取");
  await expect(note).not.toContainText("搭機證明");
});

test("還缺另一份沒有提醒：維持折疊，摘要有份數、不算有提醒（票 #305）", async ({ page }) => {
  const id = await setupClaimIncident(page, "honest-lack-quiet");
  await page.goto(`/incident/${id}`);
  await mockUploadResponse(page, {
    todo_complete: false,
    reason: "已收到，還缺登機證（或改傳一份搭機證明）",
  });
  await page.getByTestId("doc-file").setInputFiles(pdf("延誤證明.pdf"));
  const summary = page.getByTestId("upload-summary");
  await expect(summary).toContainText("1 份已收到、還缺其他文件", { timeout: SLOW });
  await expect(summary).not.toContainText("有提醒");
  await expect(page.getByTestId("upload-row")).toHaveCount(0);
  await page.getByTestId("upload-detail-toggle").click();
  await expect(page.getByTestId("upload-result")).toHaveText("符合規則，還缺登機證");
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

test("沒有存到 Google Drive：標「沒有完成」、紅字、說明 6 號的原因，也不能選待辦", async ({
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
  const red = await themeColor(page, "danger-ink");
  await expect(row.getByTestId("upload-result")).toHaveCSS("color", red);
  await expect(row.getByTestId("upload-note")).toHaveCSS("color", red);
  await expect(row.getByTestId("upload-note")).toContainText("還沒有 Google 授權");
  await expect(row.getByTestId("upload-note")).toContainText("待辦還沒有勾");
  await expect(row.getByTestId("upload-note")).not.toContainText("這份沒有存到");
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
  await expect(page.getByTestId("upload-steps")).toHaveCount(0);
  expect(await overflow()).toBe(false);
});

// 票 #301：辨識器沒有「重新檢查」時，後端退回「使用者確認」，回應是已確認、待辦已完成。
// 用 page.route 模擬那個回應（假 6 號有實作重新檢查，走不到這條路徑）：那一列不能再問一次。
test("辨識器沒有重新檢查：選了待辦確認後，那一列顯示已打勾，不再出現「需要你確認」與選擇器", async ({
  page,
}) => {
  const id = await setupClaimIncident(page, "recheck-fallback");
  await page.route("**/api/v1/incidents/*/documents/*/recheck", async (route) => {
    const documentId = route.request().url().split("/documents/")[1]?.split("/")[0];
    const { todo_id } = route.request().postDataJSON() as { todo_id: string };
    await route.fulfill({
      json: {
        id: documentId,
        file_name: "隨便一份.pdf",
        recognition_status: "recognized",
        document_kind: null,
        todo_id,
        reason: null,
        todo_complete: true,
        appended: false,
        stored: true,
      },
    });
  });
  await page.goto(`/incident/${id}`);
  await page.getByTestId("doc-file").setInputFiles(pdf("隨便一份.pdf"));
  const chooser = page.getByTestId("upload-chooser");
  await expect(chooser).toBeVisible({ timeout: SLOW });
  await chooser.getByRole("combobox").selectOption({ index: 1 });
  await chooser.getByTestId("chooser-submit").click();

  await expect(chooser).toHaveCount(0, { timeout: SLOW });
  const summary = page.getByTestId("upload-summary");
  await expect(summary).toContainText("1 份已自動打勾");
  await expect(summary).not.toContainText("需要你確認");
  await page.getByTestId("upload-detail-toggle").click();
  const row = page.getByTestId("upload-row");
  await expect(row).toHaveCount(1);
  await expect(row.getByTestId("upload-result")).toHaveText("符合規則，已自動打勾");
  await expect(row).not.toContainText("需要你確認");
  await expect(row.getByTestId("upload-chooser")).toHaveCount(0);
  await page.unrouteAll({ behavior: "ignoreErrors" });
});
