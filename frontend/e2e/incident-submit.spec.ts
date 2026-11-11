import { expect, type Page, test } from "@playwright/test";
import { expectPaper, login } from "./helpers";

// 2-5 送件（/incident/$id/submit）：先問代寄或自己處理 → 確認信件（填空格與收件者）→ 確定寄出 → 結案。
// 測試登入沒有 Google 授權，不問授權；7 號用離線實作產信。需要 make seed。
const SLOW = 15_000;

async function setup(page: Page, name: string, options: { ready: boolean }) {
  await login(page, `e2e-submit-${name}-${Date.now()}@example.com`);
  const api = page.request;
  const sums = await (await api.get("/api/v1/plans/fubon_advanced/sum-insured-options")).json();
  const policy = await (
    await api.post("/api/v1/policies/manual", {
      data: {
        plan_id: "fubon_advanced",
        sum_insured: sums.sum_insured[0],
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
  if (!created.incident)
    throw new Error(`POST incidents 回 ${createdRes.status()}：${JSON.stringify(created)}`);
  const id: string = created.incident.incident_id;
  for (let i = 0; i < 15; i++) {
    const res = await api.post(`/api/v1/incidents/${id}/messages`, {
      data: { content: "不知道" },
    });
    const reply = await res.json();
    if (!reply.reply) throw new Error(`POST messages 回 ${res.status()}：${JSON.stringify(reply)}`);
    if (reply.reply.finished) break;
  }
  if (options.ready) {
    const ctx = await (await api.get(`/api/v1/incidents/${id}`)).json();
    for (const t of ctx.todos) {
      await api.patch(`/api/v1/incidents/${id}/todos/${t.id}`, { data: { is_done: true } });
    }
  }
  return id;
}

test.beforeEach(async ({ request }) => {
  const config = await (await request.get("/api/v1/auth/config")).json();
  test.skip(!config.dev_login, "後端沒有設 DEV_LOGIN_ENABLED=true");
  test.skip(!(await request.get("/api/v1/plans")).ok(), "條款庫沒有載入，先 make seed");
});

test("待辦沒完成：說明還缺什麼，兩個選項都不能按；沒有舊的步驟列", async ({ page }) => {
  const id = await setup(page, "notready", { ready: false });
  await page.goto(`/incident/${id}/submit`);
  await expectPaper(page);

  await expect(page.getByRole("heading", { level: 1 })).toHaveText("送件");
  await expect(page.getByRole("navigation", { name: "理賠步驟" })).toHaveCount(0);
  await expect(page.getByTestId("ready")).toContainText("還有");
  await expect(page.getByTestId("ready").getByRole("link", { name: "上傳文件" })).toBeVisible();
  await expect(page.getByTestId("choose-self")).toBeDisabled();
  await expect(page.getByTestId("choose-send")).toBeDisabled();
});

test("備齊後：問寄送方式，進預覽，空格與收件者填完才能寄出，寄出前先確認", async ({ page }) => {
  const id = await setup(page, "send", { ready: true });
  await page.goto(`/incident/${id}/submit`);

  await expect(page.getByTestId("ready")).toContainText("可以送件");
  // 備齊時畫面上沒有那一行說明（只留給讀屏）；兩個按鈕並排靠左，不是分在兩端
  const readyBox = await page.getByTestId("ready").boundingBox();
  expect(readyBox && readyBox.width <= 2 && readyBox.height <= 2).toBeTruthy();
  const self = await page.getByTestId("choose-self").boundingBox();
  const send = await page.getByTestId("choose-send").boundingBox();
  expect(self && send && send.x - (self.x + self.width) < 40).toBeTruthy();
  await expect(page.getByTestId("ask")).toContainText("要由我們用你的 Gmail 幫你寄給保險公司嗎？");
  await expect(page.getByTestId("ask")).toContainText("兩個選項都會讓這筆理賠結案");
  await page.getByTestId("choose-send").click();

  // 確認信件：逐列顯示收件者、寄件者、主旨、內文、附件
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("確認信件");
  const preview = page.getByTestId("preview");
  await expect(preview.getByText("收件者", { exact: true })).toBeVisible({ timeout: SLOW });
  await expect(preview.getByText("寄件者", { exact: true })).toBeVisible();
  await expect(preview.getByText("主旨", { exact: true })).toBeVisible();
  await expect(preview.getByText("內文", { exact: true })).toBeVisible();
  // 附件欄只列檔案，沒有「共 N 份」
  await expect(preview.getByText(/^共 \d+ 份$/)).toHaveCount(0);
  await expect(preview.getByText("附件", { exact: true })).toBeVisible();
  await expect(page.getByTestId("letter-sender")).toContainText("@example.com");

  // 收件者沒填或格式不對：說明原因，寄出停用
  const submit = page.getByTestId("submit");
  const recipient = page.getByTestId("letter-recipient");
  await recipient.fill("");
  await expect(page.getByTestId("recipient-problem")).toContainText("請填寫收件者");
  await expect(submit).toBeDisabled();
  await recipient.fill("不是信箱");
  await expect(page.getByTestId("recipient-problem")).toContainText("格式不對");
  // 空格（平台抓不到的資料）：有的話錯誤列說還有幾處，填完才能寄出
  const blanks = page.getByTestId("blank");
  if ((await blanks.count()) > 0) {
    await expect(page.getByTestId("missing")).toContainText("處「（請填寫）」要填");
    await recipient.fill("claims@example.com");
    await expect(submit).toBeDisabled();
    for (const input of await blanks.all()) await input.fill("測試資料");
    await expect(page.getByTestId("missing")).toHaveCount(0);
  }
  await recipient.fill("claims@example.com");
  await expect(page.getByTestId("recipient-problem")).toHaveCount(0);
  await expect(submit).toBeEnabled();

  // 寄出前先確認；取消就留在預覽，確定才結案
  await submit.click();
  const dialog = page.getByTestId("send-confirm-dialog");
  await expect(dialog).toContainText("確定寄出？");
  await dialog.getByRole("button", { name: "取消" }).click();
  await expect(preview).toBeVisible();
  await submit.click();
  await page.getByTestId("send-confirm").click();
  await expect(page.getByTestId("closed")).toContainText("已用你的 Gmail 寄給保險公司", {
    timeout: SLOW,
  });
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("送件結果");
  // 結案後的反灰按鈕與回理賠頁
  await page.getByRole("button", { name: "下載全部文件" }).click({ force: true });
  await expect(page.getByTestId("toast")).toHaveText("暫無作用");
  await page.getByRole("link", { name: "回理賠頁" }).click();
  await expect(page).toHaveURL(new RegExp(`/incident/${id}$`));
});

test("預覽按取消回到詢問，已填的內容不會寄出", async ({ page }) => {
  const id = await setup(page, "cancel", { ready: true });
  await page.goto(`/incident/${id}/submit`);
  await page.getByTestId("choose-send").click();
  await expect(page.getByTestId("preview")).toBeVisible();
  await page.getByTestId("preview-cancel").click();
  await expect(page.getByTestId("ask")).toBeVisible();
  const ctx = await (await page.request.get(`/api/v1/incidents/${id}`)).json();
  expect(ctx.status).toBe("open");
});

test("自己處理就好：草稿詢問對話框，取消就不建草稿並結案", async ({ page }) => {
  const id = await setup(page, "self", { ready: true });
  await page.goto(`/incident/${id}/submit`);
  await page.getByTestId("choose-self").click();
  const dialog = page.getByTestId("draft-question");
  await expect(dialog).toContainText("都會結案");
  await dialog.getByRole("button", { name: "取消" }).click();
  await expect(page.getByTestId("closed")).toContainText("沒有建立草稿", { timeout: SLOW });
  await expect(page.getByTestId("closed-banner")).toContainText("只能查看");
  // 已結案：再進送件頁看到的是結果，不是詢問
  await page.goto(`/incident/${id}/submit`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("送件結果");
  await expect(page.getByTestId("ask")).toHaveCount(0);
});

test("手機寬度（390px）下 2-5 沒有橫向捲動；詢問的按鈕照順序、內容寬度；預覽的取消與寄出同一列", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 800 });
  const id = await setup(page, "mobile", { ready: true });
  await page.goto(`/incident/${id}/submit`);
  // 詢問畫面：「我自己處理就好」在上、「小助理幫我送出」在下，都是內容寬度，不撐滿
  const self = await page.getByTestId("choose-self").boundingBox();
  const send = await page.getByTestId("choose-send").boundingBox();
  expect(self && send && self.y < send.y).toBeTruthy();
  expect(self && send && self.width < 300 && send.width < 340).toBeTruthy();
  await page.screenshot({ path: "test-results/shots/mobile_2-5_ask.png" });

  await page.getByTestId("choose-send").click();
  await expect(page.getByTestId("letter-body")).toBeVisible({ timeout: SLOW });
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(overflow).toBe(false);
  // 預覽：取消在左、寄出在右，同一列
  const cancel = await page.getByTestId("preview-cancel").boundingBox();
  const submit = await page.getByTestId("submit").boundingBox();
  expect(cancel && submit && cancel.x < submit.x).toBeTruthy();
  expect(cancel && submit && Math.abs(cancel.y - submit.y) < 8).toBeTruthy();
  await page.screenshot({ path: "test-results/shots/mobile_2-5_letter.png", fullPage: true });
});
