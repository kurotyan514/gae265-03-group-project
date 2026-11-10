import { expect, type Page, test } from "@playwright/test";
import { login } from "./helpers";

// 上傳理賠文件（設計稿 v3.7 把 2-4 併進 2-3）：理賠頁待辦上方的上傳框、舊的 /documents 網址導回、送件區的上傳連結。
// 用假 6 號：依檔名辨識（含「延誤證明」之類關鍵字通過，認不出來的是需要你確認）。需要 make seed。
const SLOW = 15_000;
const pdf = (name: string) => ({
  name,
  mimeType: "application/pdf",
  buffer: Buffer.from("%PDF-1.4"),
});

async function setup(page: Page, name: string) {
  await login(page, `e2e-docs-${name}-${Date.now()}@example.com`);
  const api = page.request;
  const options = await (await api.get("/api/v1/plans/fubon_advanced/sum-insured-options")).json();
  const policy = await (
    await api.post("/api/v1/policies/manual", {
      data: {
        plan_id: "fubon_advanced",
        sum_insured: options.sum_insured[0],
        start_date: "2026-07-05",
        end_date: "2026-07-10",
      },
    })
  ).json();
  await api.patch(`/api/v1/policies/${policy.id}`, { data: { destination: "日本" } });
  const createdRes = await api.post(`/api/v1/policies/${policy.id}/incidents`, {
    data: { description: "班機延誤了六小時" },
  });
  const created = await createdRes.json();
  // 準備資料時伺服器回了錯誤：把狀態碼與內容丟出來，才看得到真正原因
  if (!created.incident)
    throw new Error(`POST incidents 回 ${createdRes.status()}：${JSON.stringify(created)}`);
  const id: string = created.incident.incident_id;
  for (let i = 0; i < 15; i++) {
    const res = await api.post(`/api/v1/incidents/${id}/messages`, {
      data: { content: "不知道" },
    });
    const reply = await res.json();
    // 準備資料時伺服器回了錯誤：直接把狀態碼與內容丟出來，才看得到真正原因
    if (!reply.reply) throw new Error(`POST messages 回 ${res.status()}：${JSON.stringify(reply)}`);
    if (reply.reply.finished) break;
  }
  return id;
}

test.beforeEach(async ({ request }) => {
  const config = await (await request.get("/api/v1/auth/config")).json();
  test.skip(!config.dev_login, "後端沒有設 DEV_LOGIN_ENABLED=true");
  test.skip(!(await request.get("/api/v1/plans")).ok(), "條款庫沒有載入，先 make seed");
});

test("舊的 /documents 網址導回理賠頁並捲到上傳框，授權結果參數照帶", async ({ page }) => {
  const id = await setup(page, "redirect");
  await page.goto(`/incident/${id}/documents?google_auth=granted`);
  await expect(page).toHaveURL(new RegExp(`/incident/${id}(\\?[^#]*)?#upload-box$`));
  await expect(page.getByTestId("trip-title")).toBeVisible();
  await expect(page.getByTestId("upload-box")).toBeVisible();
  await expect(page.getByText("已完成 Google 授權。")).toBeVisible();
  // 網址上的授權結果顯示後就拿掉，重新整理不會再出現
  await expect(page).not.toHaveURL(/google_auth/);
});

test("送件區的「上傳文件」捲到上傳框，不再離開理賠頁", async ({ page }) => {
  const id = await setup(page, "sendbox");
  await page.goto(`/incident/${id}`);
  const link = page.getByTestId("send-box").getByRole("link", { name: "上傳文件" });
  await expect(link).toHaveAttribute("href", "#upload-box");
  await link.click();
  await expect(page).toHaveURL(new RegExp(`/incident/${id}#upload-box$`));
});

test("選好檔案就上傳辨識，可一次選多份，摘要與待辦同步更新", async ({ page }) => {
  const id = await setup(page, "upload");
  await page.goto(`/incident/${id}`);
  await expect(page.getByTestId("upload-summary")).toHaveCount(0); // 上傳前沒有摘要

  await page.getByTestId("doc-file").setInputFiles([pdf("延誤證明.pdf"), pdf("機票與登機證.pdf")]);
  // 系統會把檔案依「事故類型_待辦名稱_序號」改名，所以不比對原檔名，只看份數與結果
  await expect(page.getByTestId("upload-summary")).toContainText("這次上傳 2 份", {
    timeout: SLOW,
  });
  // 假 6 號把「證明」辨識通過並打勾，另一份要使用者確認；摘要預設只列要注意的那一份
  await expect(page.getByTestId("upload-summary")).toContainText("1 份已自動打勾");
  await expect(page.getByTestId("upload-summary")).toContainText("1 份需要你確認");
  await expect(page.getByTestId("upload-row")).toHaveCount(1);
  await expect(page.getByTestId("upload-result")).toHaveText("需要你確認");
  await page.getByTestId("upload-detail-toggle").click();
  await expect(page.getByTestId("upload-row")).toHaveCount(2);
  await expect(page.getByTestId("upload-progress")).toContainText("符合規則，已自動打勾");
  // 通過的文件由 6 號勾起待辦，待辦清單同步更新
  await expect(page.getByTestId("todos").getByText("AI 已打勾").first()).toBeVisible();
});

test("無法辨識的文件：在上傳框裡選對應的待辦後確認", async ({ page }) => {
  const id = await setup(page, "review");
  await page.goto(`/incident/${id}`);

  await page.getByTestId("doc-file").setInputFiles(pdf("隨便一份.pdf"));
  const chooser = page.getByTestId("upload-chooser");
  await expect(chooser).toBeVisible({ timeout: SLOW });
  const submit = chooser.getByTestId("chooser-submit");
  await expect(submit).toBeDisabled();
  await chooser.getByRole("combobox").selectOption({ index: 1 });
  await expect(submit).toBeEnabled();
  await submit.click();
  await expect(chooser).toHaveCount(0, { timeout: SLOW });
});

test("2-3 理賠頁待辦上方有上傳入口：進度、摘要與說明", async ({ page }) => {
  const id = await setup(page, "trip-upload");
  await page.goto(`/incident/${id}`);
  const docFile = page.getByTestId("doc-file");
  await expect(docFile).toBeAttached();
  // ? 說明預設收起
  await expect(page.getByText("10 MB 內")).toHaveCount(0);
  await page.getByTestId("upload-help-toggle").click();
  await expect(page.getByText("10 MB 內")).toBeVisible();
  await page.getByTestId("upload-help-toggle").click(); // 收起，免得蓋住下面的按鈕

  await docFile.setInputFiles([pdf("延誤證明.pdf"), pdf("隨便一份.pdf")]);
  await expect(page.getByTestId("upload-summary")).toContainText("這次上傳 2 份", {
    timeout: SLOW,
  });
  await expect(page.getByTestId("upload-summary")).toContainText("需要你確認");
  await page.getByTestId("upload-detail-toggle").click();
  await expect(page.getByTestId("upload-row")).toHaveCount(2);
  await expect(page.getByTestId("todos").getByText("AI 已打勾").first()).toBeVisible();
});

test("手機寬度（390px）下上傳區沒有橫向捲動", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  const id = await setup(page, "mobile");
  await page.goto(`/incident/${id}`);
  await page.getByTestId("doc-file").setInputFiles([pdf("延誤證明.pdf"), pdf("隨便一份.pdf")]);
  await expect(page.getByTestId("upload-summary")).toContainText("這次上傳 2 份", {
    timeout: SLOW,
  });
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(overflow).toBe(false);
});
