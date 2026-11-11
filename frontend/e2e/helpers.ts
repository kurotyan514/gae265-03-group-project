import { expect, type Page, test } from "@playwright/test";

/**
 * 用測試登入（任何 email 都能登入，需要後端開 DEV_LOGIN_ENABLED）。
 * 登入後輪詢 `/auth/me` 直到回 200 才回來：只等網址變成首頁，並行時登入狀態偶爾還沒生效，
 * 接著用 `page.request` 打 API 就會 401「未登入」。
 */
export async function login(page: Page, email: string) {
  await page.goto("/login?next=%2F");
  await page.getByLabel("Email").fill(email);
  await page.getByRole("button", { name: "測試登入" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect
    .poll(async () => (await page.request.get("/api/v1/auth/me")).status(), { timeout: 10_000 })
    .toBe(200);
}

/** 後台的測試用管理者：後端的 `ADMIN_EMAILS` 要包含它（.env.example 已有）。 */
export const ADMIN_EMAIL = "e2e-admin@example.com";

/** 已用測試登入之後呼叫：目前登入的人不是管理者就略過（通常是本機 .env 的 ADMIN_EMAILS 沒有 ADMIN_EMAIL）。 */
export async function skipUnlessAdmin(page: Page) {
  const me = await (await page.request.get("/api/v1/auth/me")).json();
  test.skip(!me.is_admin, `後端的 ADMIN_EMAILS 要包含 ${ADMIN_EMAIL}（見 .env.example）`);
}

/** 設計稿功能二的頁面底色是米白（--color-paper）：標了 `data-page-paper` 的頁面，body 換成這個底色。 */
export async function expectPaper(page: Page) {
  await expect(page.locator("body")).toHaveCSS("background-color", "rgb(251, 250, 246)");
}

/** 登入、建一張保單與一個延誤事故，並和 5 號聊到待辦產生；回事故 id（假 6 號依檔名辨識，需要 make seed）。 */
export async function setupClaimIncident(page: Page, name: string) {
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
