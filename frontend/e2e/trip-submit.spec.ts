import { expect, type Page, test } from "@playwright/test";
import { login } from "./helpers";

// 行程版送件（/trip/$policyId/submit，ADR-0029）：整個行程一封信、一次送件，三種結果都結案並鎖住行程。
// 測試登入沒有 Google 授權，不問授權；7 號用離線實作產信。需要 make seed。
const SLOW = 15_000;

async function setup(page: Page, name: string, ready: boolean) {
  await login(page, `e2e-trip-submit-${name}-${Date.now()}@example.com`);
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
    const res = await api.post(`/api/v1/incidents/${id}/messages`, { data: { content: "不知道" } });
    const reply = await res.json();
    if (!reply.reply) throw new Error(`POST messages 回 ${res.status()}：${JSON.stringify(reply)}`);
    if (reply.reply.finished) break;
  }
  if (ready) {
    const trip = await (await api.get(`/api/v1/policies/${policy.id}/trip`)).json();
    const todos = [
      ...trip.shared_todos,
      ...trip.incidents.flatMap((i: { todos: unknown[] }) => i.todos),
    ];
    for (const t of todos as { id: string; applicable: boolean }[]) {
      if (t.applicable)
        await api.patch(`/api/v1/policies/${policy.id}/todos/${t.id}`, { data: { is_done: true } });
    }
  }
  return policy.id as string;
}

test.beforeEach(async ({ request }) => {
  const config = await (await request.get("/api/v1/auth/config")).json();
  test.skip(!config.dev_login, "後端沒有設 DEV_LOGIN_ENABLED=true");
  test.skip(!(await request.get("/api/v1/plans")).ok(), "條款庫沒有載入，先 make seed");
});

test("待辦沒完成：說明還缺什麼，兩個選項都不能按，連結回行程頁", async ({ page }) => {
  const policyId = await setup(page, "notready", false);
  await page.goto(`/trip/${policyId}/submit`);

  await expect(page.getByRole("heading", { level: 1 })).toHaveText("送件");
  await expect(page.getByTestId("ready")).toContainText("還有");
  await expect(page.getByTestId("choose-self")).toBeDisabled();
  await expect(page.getByTestId("choose-send")).toBeDisabled();
  await page.getByTestId("ready").getByRole("link", { name: "上傳文件" }).click();
  await expect(page).toHaveURL(new RegExp(`/trip/${policyId}#upload-box$`));
});

test("行程頁的「送件」連到送件頁；備齊後預覽、寄出、結案，行程鎖住", async ({ page }) => {
  const policyId = await setup(page, "send", true);
  await page.goto(`/trip/${policyId}`);
  await page.getByTestId("go-submit").click();
  await expect(page).toHaveURL(new RegExp(`/trip/${policyId}/submit$`));
  await expect(page.getByTestId("ask")).toContainText("要由我們用你的 Gmail 幫你寄給保險公司嗎？");
  await page.getByTestId("choose-send").click();

  await expect(page.getByRole("heading", { level: 1 })).toHaveText("確認信件");
  const preview = page.getByTestId("preview");
  await expect(preview.getByText("主旨", { exact: true })).toBeVisible({ timeout: SLOW });
  const recipient = page.getByTestId("letter-recipient");
  await recipient.fill("claims@example.com");
  const blanks = page.getByTestId("blank");
  for (const input of await blanks.all()) await input.fill("測試資料");
  await page.getByTestId("submit").click();
  await page.getByTestId("send-confirm").click();

  await expect(page.getByTestId("closed")).toContainText("已用你的 Gmail 寄給保險公司", {
    timeout: SLOW,
  });
  await expect(page.getByTestId("closed")).toContainText("此行程已結案");
  // 寄出後跳出說明視窗（信在 Gmail 的寄件備份），關掉後才看得到頁面
  const gmail = page.getByTestId("gmail-result-dialog");
  await expect(gmail).toContainText("寄件備份");
  await gmail.getByRole("button", { name: "關閉" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("送件結果");

  // 回行程頁：已結案、送件區說明寄出、不能再勾
  await page.getByRole("link", { name: "回行程頁" }).click();
  await expect(page).toHaveURL(new RegExp(`/trip/${policyId}$`));
  await expect(page.getByTestId("send-closed")).toContainText("已替你送件");
  await expect(page.getByTestId("todos").getByRole("checkbox").first()).toBeDisabled();
});

test("自己處理就好：不建草稿，直接結案", async ({ page }) => {
  const policyId = await setup(page, "self", true);
  await page.goto(`/trip/${policyId}/submit`);
  await page.getByTestId("choose-self").click();
  await page.getByRole("button", { name: "取消" }).click(); // 草稿詢問：取消＝不建草稿
  await expect(page.getByTestId("closed")).toContainText("沒有建立草稿", { timeout: SLOW });
  await expect(page.getByTestId("closed-banner")).toBeVisible();
});
