import { expect, type Page, test } from "@playwright/test";
import { expectPaper, login } from "./helpers";

// 2-3 理賠頁（/incident/$id，事件問完之後）：狀態列、狀況總結、待辦、送件區、問答、結案唯讀。
// 事件用 API 快速備好（假 5 號問到結束）。需要測試登入與條款庫、方案資料（make seed）。
const SLOW = 15_000;

async function setup(page: Page, name: string) {
  await login(page, `e2e-trip-page-${name}-${Date.now()}@example.com`);
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
  // 問到 5 號回報事故類型為止
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

test("問完後顯示理賠頁：狀態列、狀況總結、待辦兩張卡、送件區、問答", async ({ page }) => {
  const id = await setup(page, "overview");
  await page.goto(`/incident/${id}`);
  await expectPaper(page);

  // 狀態列：目的地與期間、方案與保額、進度 Pill；沒有舊的步驟列
  await expect(page.getByTestId("trip-title")).toHaveText("日本 2026/07/05～07/10");
  await expect(page.getByText("富邦國外旅平險-進階型 ·")).toBeVisible();
  await expect(page.getByText(/待辦 \d+／\d+/)).toBeVisible();
  await expect(page.getByRole("navigation", { name: "理賠步驟" })).toHaveCount(0);
  // 狀況總結：事故卡
  await expect(page.getByTestId("incident-type")).toContainText("班機延誤");
  await expect(page.getByTestId("facts")).toBeVisible();
  await expect(page.getByTestId("clauses")).toBeVisible();
  // 待辦：事故當下與回國後整理兩張卡，整個行程的理賠申請書在最後一組
  const todos = page.getByTestId("todos");
  await expect(todos.getByRole("region", { name: "事故當下" })).toBeVisible();
  await expect(todos.getByRole("region", { name: "回國後整理" })).toBeVisible();
  await expect(todos.getByRole("heading", { name: "整個行程" })).toBeVisible();
  await expect(todos.getByText("填寫理賠申請書")).toBeVisible();
  // 送件區：還缺文件時有「上傳文件」；問答卡有提問列
  await expect(page.getByTestId("send-box")).toContainText("還缺");
  // 待辦區上方有唯一的上傳入口
  await expect(page.getByRole("heading", { name: "理賠待辦" })).toBeVisible();
  await expect(page.getByTestId("doc-file")).toBeAttached();
  await expect(page.getByTestId("message")).toHaveAttribute(
    "placeholder",
    "關於這次理賠的任何問題",
  );
});

test("有新狀況：在問答框裡，點了用同一張保單開新事件", async ({ page }) => {
  const id = await setup(page, "new-situation");
  await page.goto(`/incident/${id}`);

  const qa = page.getByRole("region", { name: "問答" });
  await qa.getByRole("link", { name: /有新狀況/ }).click();

  await expect(page).toHaveURL(/\/incident\/new\/[0-9a-f-]{36}$/);
  await expect(page.getByText("富邦國外旅平險-進階型 ·")).toBeVisible();
});

test("勾不需上傳的待辦：進度更新；需上傳但沒有文件的待辦先跳確認，確認後標未附文件", async ({
  page,
}) => {
  const id = await setup(page, "tick");
  await page.goto(`/incident/${id}`);
  const todos = page.getByTestId("todos");
  const progress = page.getByText(/待辦 \d+／\d+/);
  const before = await progress.textContent();

  // 需上傳的待辦（理賠申請書沒有文件）：先確認，取消就不勾
  const form = todos.getByRole("listitem").filter({ hasText: "填寫理賠申請書" });
  const box = form.getByRole("checkbox");
  await box.click();
  const dialog = page.getByTestId("tick-dialog");
  await expect(dialog).toContainText("尚未確認文件，確定要打勾嗎？");
  await expect(dialog).toContainText("只附上已上傳的文件");
  await dialog.getByRole("button", { name: "回待辦清單" }).click();
  await expect(box).not.toBeChecked();
  expect(await progress.textContent()).toBe(before);

  // 再勾一次、確認：打勾並標「未附文件」，進度加一
  await box.click();
  await page.getByTestId("tick-confirm").click();
  await expect(box).toBeChecked();
  await expect(form).toContainText("未附文件");
  expect(await progress.textContent()).not.toBe(before);
});

test("系統確認的待辦取消勾選前會先問", async ({ page }) => {
  const id = await setup(page, "undo");
  // 上傳一份文件：假 6 號辨識通過，由系統勾起該待辦
  const uploaded = await page.request.post(`/api/v1/incidents/${id}/documents`, {
    multipart: {
      file: { name: "延誤證明.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4") },
    },
  });
  expect(uploaded.ok()).toBeTruthy();
  await page.goto(`/incident/${id}`);

  const agentDone = page
    .getByTestId("todos")
    .getByRole("listitem")
    .filter({ hasText: "AI 已打勾" })
    .first();
  await expect(agentDone).toBeVisible({ timeout: SLOW });
  // 系統會依「事故類型_待辦名稱_序號」把檔案改名，所以看不到原檔名
  await expect(agentDone.getByTestId("todo-files")).toContainText("班機延誤_");
  const box = agentDone.getByRole("checkbox");
  await expect(box).toBeChecked();
  await box.click();
  const dialog = page.getByTestId("undo-dialog");
  await expect(dialog).toContainText("系統看過你的文件後確認的");
  await dialog.getByRole("button", { name: "保留" }).click();
  await expect(box).toBeChecked();
});

test("事故卡預設展開，點標題收合；有待確認事項時標題旁顯示「待確認 N」", async ({ page }) => {
  const id = await setup(page, "card");
  await page.goto(`/incident/${id}`);
  const head = page.getByTestId("incident-type");
  await expect(head).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByTestId("facts")).toBeVisible();
  // 待確認的數量依事件資料：有才顯示，數字要對得上；沒有就不顯示
  const ctx = await (await page.request.get(`/api/v1/incidents/${id}`)).json();
  const unsure = (ctx.clauses ?? []).filter(
    (c: { conclusion: string }) => c.conclusion === "insufficient",
  ).length;
  const badge = page.getByTestId("unsure-count");
  if (unsure > 0) await expect(badge).toHaveText(`待確認 ${unsure}`);
  else await expect(badge).toHaveCount(0);
  await head.click();
  await expect(head).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByTestId("facts")).toBeHidden();
  // 收合時標題與待確認數仍在
  await expect(head).toContainText("班機延誤");
  if (unsure > 0) await expect(badge).toBeVisible();
  await head.click();
  await expect(page.getByTestId("facts")).toBeVisible();
});

test("待辦是單行加狀態晶片，點一行展開看檔案與說明；手機晶片排在名稱下一行", async ({ page }) => {
  const id = await setup(page, "rows");
  const uploaded = await page.request.post(`/api/v1/incidents/${id}/documents`, {
    multipart: {
      file: { name: "延誤證明.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4") },
    },
  });
  expect(uploaded.ok()).toBeTruthy();
  await page.goto(`/incident/${id}`);

  const todos = page.getByTestId("todos");
  // 沒附檔的待辦是「待上傳」，附了檔的是「1 份檔案」
  await expect(todos.getByTestId("todo-status").filter({ hasText: "1 份檔案" })).toHaveCount(1, {
    timeout: SLOW,
  });
  await expect(
    todos.getByTestId("todo-status").filter({ hasText: "待上傳" }).first(),
  ).toBeVisible();
  // 預設收合：檔案清單在畫面上看不到，點一行才展開
  const row = todos.getByRole("listitem").filter({ hasText: "AI 已打勾" }).first();
  await expect(row.getByTestId("todo-files")).toBeHidden();
  const toggle = row.getByTestId("todo-toggle");
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect(row.getByTestId("todo-files")).toBeVisible();
  // 點名稱展開不會動到勾選框
  await expect(row.getByRole("checkbox")).toBeChecked();

  await page.setViewportSize({ width: 390, height: 800 });
  const name = await row.getByTestId("todo-toggle").locator("span").first().boundingBox();
  const chip = await row.getByTestId("todo-status").boundingBox();
  expect(name && chip && chip.y >= name.y + name.height - 1).toBeTruthy();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(overflow).toBe(false);
  await page.screenshot({ path: "test-results/shots/mobile_2-3_rows.png", fullPage: true });
});

test("問答：在理賠頁提問，回覆出現在對話裡", async ({ page }) => {
  const id = await setup(page, "qa");
  await page.goto(`/incident/${id}`);
  const chat = page.getByTestId("messages");
  await expect(chat.locator("li").first()).toBeVisible(); // 等對話載入，才數得準
  const before = await chat.locator("li").count();

  await page.getByTestId("message").fill("住宿可以賠多少？");
  await page.getByTestId("send").click();
  await expect(chat.locator("li")).toHaveCount(before + 2, { timeout: SLOW });
  await expect(page.getByText("回答由 AI 依條款整理，實際以保險公司審核為準。")).toBeVisible();
});

test("結案後唯讀：已結案 Pill、結案說明、沒有提問列，待辦只能看", async ({ page }) => {
  const id = await setup(page, "closed");
  // 待辦都勾完（需上傳的也自己勾），再選「自己處理」結案
  const ctx = await (await page.request.get(`/api/v1/incidents/${id}`)).json();
  for (const t of ctx.todos) {
    const res = await page.request.patch(`/api/v1/incidents/${id}/todos/${t.id}`, {
      data: { is_done: true },
    });
    expect(res.ok()).toBeTruthy();
  }
  const closed = await page.request.post(`/api/v1/incidents/${id}/submission`, {
    data: { mode: "self" },
  });
  expect(closed.ok()).toBeTruthy();

  await page.goto(`/incident/${id}`);
  await expect(page.getByText("已結案", { exact: true })).toBeVisible();
  await expect(page.getByTestId("closed-banner")).toContainText("只能查看");
  await expect(page.getByTestId("message")).toHaveCount(0);
  await expect(page.getByTestId("send-closed")).toBeVisible();
  await expect(page.getByTestId("todos").getByRole("checkbox").first()).toBeDisabled();
  await expect(page.getByTestId("doc-file")).toHaveCount(0);
  // 結案後的反灰按鈕
  await page.getByRole("button", { name: "到 Gmail 查看" }).click({ force: true });
  await expect(page.getByTestId("toast")).toHaveText("暫無作用");
});

test("手機寬度（390px）下理賠頁單欄、沒有橫向捲動", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  const id = await setup(page, "mobile");
  await page.goto(`/incident/${id}`);
  await expect(page.getByTestId("trip-title")).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(overflow).toBe(false);
});

test("桌機寬度（1440px）下 2-3 是雙欄：左邊內容、右邊問答；有新狀況在問答框；手機維持單欄", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const id = await setup(page, "desktop");
  await page.goto(`/incident/${id}`);
  const qa = page.getByRole("region", { name: "問答" });
  const qaBox = await qa.boundingBox();
  const todoBox = await page.getByRole("region", { name: "理賠待辦" }).boundingBox();
  expect(qaBox && todoBox && qaBox.x > todoBox.x + todoBox.width - 1).toBeTruthy();
  // 有新狀況在問答框裡，不在狀態列
  await expect(qa.getByRole("link", { name: /有新狀況/ })).toBeVisible();
  await expect(
    page.getByRole("region", { name: "行程狀態" }).getByRole("link", { name: /有新狀況/ }),
  ).toHaveCount(0);
  await page.getByTestId("todo-toggle").first().click();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: "test-results/shots/desktop_2-3.png", fullPage: true });

  await page.setViewportSize({ width: 390, height: 800 });
  const m = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(m).toBe(false);
  // 手機：問答預設收起，點右緣的圓鈕才從底部拉起，「收起」再關上
  await expect(qa).toBeHidden();
  await page.getByTestId("qa-open").click();
  await expect(qa).toBeVisible();
  const sheet = await qa.boundingBox();
  expect(sheet && sheet.y + sheet.height >= 800 - 1).toBeTruthy();
  // 面板約 75% 高（上方還看得到頁首與狀態列），輸入列與送出鈕完整在螢幕內
  expect(sheet && sheet.y > 800 * 0.15 && sheet.y < 800 * 0.4).toBeTruthy();
  const send = await qa.getByTestId("send").boundingBox();
  expect(send && send.y >= 0 && send.y + send.height <= 800).toBeTruthy();
  await page.screenshot({ path: "test-results/shots/mobile_2-3_qa_open.png" });
  await page.getByTestId("qa-close").click();
  await expect(qa).toBeHidden();
});
