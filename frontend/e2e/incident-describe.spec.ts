import { expect, type Page, test } from "@playwright/test";
import { login } from "./helpers";

// 2-2 描述事故：建立前（/incident/new/$policyId）旅客送出第一句才建立事件；追問中（/incident/$id）選項 Chip 與提問列。
// 用假 5 號：第一個追問附三個選項。需要測試登入與條款庫、方案資料（make seed）。
const SLOW = 15_000;

async function loginWithPolicy(page: Page, name: string) {
  await login(page, `e2e-describe-${name}-${Date.now()}@example.com`);
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
  return policy.id as string;
}

test.beforeEach(async ({ request }) => {
  const config = await (await request.get("/api/v1/auth/config")).json();
  test.skip(!config.dev_login, "後端沒有設 DEV_LOGIN_ENABLED=true");
  test.skip(!(await request.get("/api/v1/plans")).ok(), "條款庫沒有載入，先 make seed");
});

test("建立前：頁首帶保單的目的地與期間，只有固定第一句；沒送出就離開不會留下事件", async ({
  page,
}) => {
  const policyId = await loginWithPolicy(page, "before");

  await page.goto(`/incident/new/${policyId}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("日本 2026/07/05～07/10");
  await expect(page.getByText("富邦國外旅平險-進階型 ·")).toBeVisible();
  const chat = page.getByTestId("messages");
  await expect(chat.locator("li")).toHaveCount(1);
  await expect(chat).toContainText("發生什麼事了？用一兩句話描述就好");
  await expect(page.getByTestId("quick-replies")).toHaveCount(0);
  // 輸入框為空時送出 disabled；有字才啟用，計數即時更新（上限 500）
  const send = page.getByTestId("send");
  await expect(send).toBeDisabled();
  await page.getByTestId("message").fill("班機延誤了");
  await expect(page.getByText("5/500")).toBeVisible();
  await expect(send).toBeEnabled();

  // 沒送出就離開：不會有事件
  await page.goto("/");
  const incidents = await (await page.request.get("/api/v1/incidents")).json();
  expect(incidents).toHaveLength(0);
});

test("建立前：送出第一句才建立事件，換到追問畫面；回上一步仍是同一份保單", async ({ page }) => {
  const policyId = await loginWithPolicy(page, "send");

  await page.goto(`/incident/new/${policyId}`);
  await page.getByRole("link", { name: "上一步" }).click();
  await expect(page).toHaveURL(new RegExp(`/incident/new\\?policy=${policyId}$`));
  await page.goBack();

  await page.getByTestId("message").fill("班機延誤了六小時");
  await page.getByTestId("send").click();
  await expect(page).toHaveURL(/\/incident\/[0-9a-f-]{36}$/, { timeout: SLOW });
  // 開場白、旅客的第一句、5 號的第一個追問（附選項）
  await expect(page.getByTestId("messages").locator("li")).toHaveCount(3, { timeout: SLOW });
  await expect(
    page.getByTestId("quick-replies").getByRole("button", { name: "生病受傷" }),
  ).toBeVisible();
  const incidents = await (await page.request.get("/api/v1/incidents")).json();
  expect(incidents).toHaveLength(1);
  // 換路由是取代：按上一頁不會回到空的對話
  await page.goBack();
  await expect(page).not.toHaveURL(new RegExp(`/incident/new/${policyId}$`));
});

test("追問中：頁首沿用保單資訊、沒有舊的標題與步驟列，點選項就是回答", async ({ page }) => {
  const policyId = await loginWithPolicy(page, "clarify");
  const createdRes = await page.request.post(`/api/v1/policies/${policyId}/incidents`, {
    data: { description: "班機延誤了六小時" },
  });
  const created = await createdRes.json();
  // 準備資料時伺服器回了錯誤：把狀態碼與內容丟出來，才看得到真正原因
  if (!created.incident)
    throw new Error(`POST incidents 回 ${createdRes.status()}：${JSON.stringify(created)}`);

  await page.goto(`/incident/${created.incident.incident_id}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("日本 2026/07/05～07/10");
  await expect(page.getByRole("navigation", { name: "理賠步驟" })).toHaveCount(0);
  await expect(page.getByTestId("message")).toHaveAttribute(
    "placeholder",
    "回答上面的問題，或點選項",
  );

  // 點選項：送出並收到下一句；舊問題的選項不再出現
  await page.getByTestId("quick-replies").getByRole("button", { name: "班機延誤" }).click();
  await expect(page.getByTestId("messages").locator("li")).toHaveCount(5, { timeout: SLOW });
  await expect(page.getByTestId("quick-replies")).toHaveCount(0);
  await expect(page.getByTestId("message")).toHaveAttribute("placeholder", "回答上面的問題");
});

test("手機寬度（390px）下 2-2 沒有橫向捲動，提問列上下排", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  const policyId = await loginWithPolicy(page, "mobile");
  await page.goto(`/incident/new/${policyId}`);
  await expect(page.getByTestId("message")).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(overflow).toBe(false);
  const input = await page.getByTestId("message").boundingBox();
  const submit = await page.getByTestId("send").boundingBox();
  expect(input && submit && submit.y > input.y + input.height - 1).toBeTruthy();
});

test("2-2 送出後顯示「正在整理理賠項目」遮罩，桌機仍是單欄", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const policyId = await loginWithPolicy(page, "overlay");
  // 讓建立事件的請求慢一點，才看得到遮罩
  await page.route("**/api/v1/policies/*/incidents", async (route) => {
    await new Promise((r) => setTimeout(r, 1500));
    await route.continue();
  });
  await page.goto(`/incident/new/${policyId}`);
  const chat = await page.getByTestId("messages").boundingBox();
  expect(chat && chat.width > 700).toBeTruthy();
  await page.getByTestId("message").fill("班機延誤了六小時");
  await page.getByTestId("send").click();
  await expect(page.getByTestId("busy")).toHaveText("正在整理理賠項目…");
  await page.screenshot({ path: "test-results/shots/desktop_2-2_loading.png" });
  await expect(page).toHaveURL(/\/incident\/[0-9a-f-]{36}$/, { timeout: SLOW });
});
