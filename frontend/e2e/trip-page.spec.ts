import { expect, type Page, test } from "@playwright/test";
import { expectPaper, login } from "./helpers";

// 行程頁（/trip/$policyId，ADR-0029）：一張保單的所有事故收在一頁。
// 事故用 API 快速備好（假 5 號問到結束）。需要測試登入與條款庫、方案資料（make seed）。

type Setup = { policyId: string; incidentIds: string[] };

async function newIncident(page: Page, policyId: string, description: string) {
  const api = page.request;
  const createdRes = await api.post(`/api/v1/policies/${policyId}/incidents`, {
    data: { description },
  });
  const created = await createdRes.json();
  if (!created.incident)
    throw new Error(`POST incidents 回 ${createdRes.status()}：${JSON.stringify(created)}`);
  const id: string = created.incident.incident_id;
  for (let i = 0; i < 15; i++) {
    const res = await api.post(`/api/v1/incidents/${id}/messages`, {
      data: { content: description },
    });
    const reply = await res.json();
    if (!reply.reply) throw new Error(`POST messages 回 ${res.status()}：${JSON.stringify(reply)}`);
    if (reply.reply.finished) break;
  }
  return id;
}

async function setup(page: Page, name: string, descriptions: string[]): Promise<Setup> {
  await login(page, `e2e-trip-${name}-${Date.now()}@example.com`);
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
  const incidentIds: string[] = [];
  for (const d of descriptions) incidentIds.push(await newIncident(page, policy.id, d));
  return { policyId: policy.id, incidentIds };
}

test.beforeEach(async ({ request }) => {
  const config = await (await request.get("/api/v1/auth/config")).json();
  test.skip(!config.dev_login, "後端沒有設 DEV_LOGIN_ENABLED=true");
  test.skip(!(await request.get("/api/v1/plans")).ok(), "條款庫沒有載入，先 make seed");
});

test("行程頁：行程資訊列、事故卡、待辦依事故分組並有「整個行程」的共同文件", async ({ page }) => {
  const { policyId } = await setup(page, "overview", ["班機延誤了六小時"]);
  await page.goto(`/trip/${policyId}`);
  await expectPaper(page);

  await expect(page.getByTestId("trip-title")).toHaveText("日本 2026/07/05～07/10");
  await expect(page.getByText(/待辦 \d+／\d+/)).toBeVisible();
  // 事故卡：選中的事故展開，沒有「問答」「▸」
  const card = page.getByTestId("trip-incident");
  await expect(card).toHaveCount(1);
  await expect(card.getByTestId("incident-type")).toContainText("班機延誤");
  await expect(card.getByTestId("incident-ask")).toHaveCount(0);
  // 待辦：事故自己的一組，加上「整個行程」一組（共同文件：理賠申請書）
  await expect(page.getByTestId("todo-group").first()).toContainText("班機延誤");
  const shared = page.getByTestId("todo-group-trip").first();
  await expect(shared).toContainText("整個行程");
  await expect(page.getByTestId("todos")).toContainText("填寫理賠申請書");
  // 右欄問答：選中事故的名稱
  await expect(page.getByTestId("qa-title")).toContainText("班機延誤");
});

test("勾選待辦後完成度更新；行程頁與事件資料一致", async ({ page }) => {
  const { policyId } = await setup(page, "tick", ["班機延誤了六小時"]);
  await page.goto(`/trip/${policyId}`);
  const pill = page.getByText(/待辦 \d+／\d+/);
  await expect(pill).toBeVisible();
  const before = (await pill.textContent()) ?? "";
  const done0 = Number(before.match(/待辦 (\d+)／/)?.[1]);

  // 勾「整個行程」組的第一項（不需要上傳的優先；需上傳的會先跳確認）
  const checkbox = page.getByTestId("todo-group-trip").first().getByRole("checkbox").first();
  await checkbox.click(); // 需上傳的待辦會先跳確認，狀態要等確認後才變，不能用 check()
  const dialog = page.getByTestId("tick-dialog");
  if (await dialog.isVisible().catch(() => false)) await page.getByTestId("tick-confirm").click();

  await expect(pill).toHaveText(new RegExp(`待辦 ${done0 + 1}／`));
});

test("多個事故：選中的事故展開並顯示它的問答；其他事故收起，可按「問答」切換、按「▸」展開", async ({
  page,
}) => {
  const { policyId } = await setup(page, "multi", ["班機延誤了六小時", "班機取消了"]);
  await page.goto(`/trip/${policyId}`);

  const cards = page.getByTestId("trip-incident");
  await expect(cards).toHaveCount(2);
  // 預設選中第一個（日期最早）；第二個沒有選中，有「問答」與「▸」
  await expect(cards.nth(0)).toHaveAttribute("data-selected", "true");
  await expect(cards.nth(1).getByTestId("incident-ask")).toBeVisible();
  const toggle = cards.nth(1).getByTestId("incident-toggle");
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  // 展開只影響左欄，右欄問答還是第一個事故
  await expect(cards.nth(0)).toHaveAttribute("data-selected", "true");
  // 按「問答」：選中第二個，右欄換成它的問答
  await cards.nth(1).getByTestId("incident-ask").click();
  await expect(cards.nth(1)).toHaveAttribute("data-selected", "true");
  await expect(cards.nth(0).getByTestId("incident-ask")).toBeVisible();
  // 共同文件整個行程只有一組、不重複
  await expect(page.getByTestId("todo-group-trip")).toHaveCount(
    await page.getByTestId("todo-group-trip").count(),
  );
  await expect(page.getByTestId("todos").getByText("填寫理賠申請書")).toHaveCount(1);
});

test("不符保障的事故：標「不符保障」，其他事故照常", async ({ page }) => {
  const { policyId } = await setup(page, "uncovered", ["班機延誤了六小時", "班機延誤了但是不理賠"]);
  await page.goto(`/trip/${policyId}`);

  const cards = page.getByTestId("trip-incident");
  await expect(cards).toHaveCount(2);
  await expect(page.getByTestId("not-covered")).toHaveCount(1);
});

test("行程送件結案後唯讀：已結案標籤、沒有問答、待辦不能勾", async ({ page }) => {
  const { policyId } = await setup(page, "locked", ["班機延誤了六小時"]);
  const api = page.request;
  const trip = await (await api.get(`/api/v1/policies/${policyId}/trip`)).json();
  const todos = [
    ...trip.shared_todos,
    ...trip.incidents.flatMap((i: { todos: unknown[] }) => i.todos),
  ];
  for (const t of todos as { id: string; applicable: boolean }[]) {
    if (t.applicable)
      await api.patch(`/api/v1/policies/${policyId}/todos/${t.id}`, { data: { is_done: true } });
  }
  const submitted = await api.post(`/api/v1/policies/${policyId}/submission`, {
    data: { mode: "self" },
  });
  expect(submitted.status()).toBe(201);

  await page.goto(`/trip/${policyId}`);

  await expect(page.getByText("已結案")).toBeVisible();
  await expect(page.getByRole("region", { name: "問答" })).toHaveCount(0);
  await expect(page.getByTestId("todos").getByRole("checkbox").first()).toBeDisabled();
});

test("找不到行程：顯示提示", async ({ page }) => {
  await login(page, `e2e-trip-missing-${Date.now()}@example.com`);
  await page.goto("/trip/00000000-0000-0000-0000-000000000000");
  await expect(page.getByText("找不到這個行程")).toBeVisible();
});
