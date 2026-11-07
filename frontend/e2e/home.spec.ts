import { expect, type Page, test } from "@playwright/test";

/** 今天往後 offset 天的 YYYY-MM-DD（瀏覽器的本地日期）。 */
function day(offset: number): string {
  const d = new Date();
  d.setDate(d.getDate() + offset);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

async function login(page: Page, email: string) {
  await page.goto("/login?next=%2F");
  await page.getByLabel("Email").fill(email);
  await page.getByRole("button", { name: "測試登入" }).click();
  await expect(page).toHaveURL(/\/$/);
}

/** 每次用新的帳號，才不會被開發資料庫裡先前留下的比較紀錄影響。 */
const freshEmail = (name: string) => `e2e-home-${name}-${Date.now()}@example.com`;

/** 直接用 API 建一筆 1-1 填完的比較紀錄（登入的 cookie 在 page.request 裡）。 */
async function createComparison(page: Page, destination: string, departOffset: number) {
  const response = await page.request.post("/api/v1/comparisons", {
    data: {
      destination,
      depart_date: day(departOffset),
      return_date: day(departOffset + 5),
      age: 30,
    },
  });
  expect(response.ok()).toBeTruthy();
}

test.beforeEach(async ({ request }) => {
  const config = await (await request.get("/api/v1/auth/config")).json();
  test.skip(!config.dev_login, "後端沒有設 DEV_LOGIN_ENABLED=true");
});

// 首頁需要登入：未登入被帶到登入頁，登入後回首頁看到 header 與兩張入口卡，登出後又被擋。
test("未登入開首頁會到登入頁，登入後看到首頁，登出後要重新登入", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login\?.*next=%2F/);

  await page.getByLabel("Email").fill("e2e-home@example.com");
  await page.getByRole("button", { name: "測試登入" }).click();

  await expect(page).toHaveURL(/\/$/);
  const header = page.getByRole("banner");
  await expect(header.getByRole("link", { name: /好險有你/ })).toHaveAttribute("href", "/");
  // dev-login 沒給名稱時以 email 當名字
  await expect(header.getByTestId("header-user")).toHaveText("e2e-home@example.com");
  // 設計稿沒有「{名字}，你現在需要什麼？」：h1 只給畫面閱讀器讀
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("首頁");

  await expect(page.getByRole("link", { name: /出發前：幫我選方案/ })).toHaveAttribute(
    "href",
    "/compare/new",
  );
  await expect(page.getByRole("link", { name: /出事了：幫我處理理賠/ })).toHaveAttribute(
    "href",
    "/incident/new",
  );

  await header.getByRole("button", { name: "登出" }).click();
  await expect(page).toHaveURL(/\/login/);

  await page.goto("/");
  await expect(page).toHaveURL(/\/login\?.*next=%2F/);
});

test("沒有比較紀錄時，最近的比較顯示空狀態", async ({ page }) => {
  await login(page, freshEmail("empty"));

  const recent = page.getByRole("region", { name: "最近的比較" });
  await expect(recent.getByText("比較過的方案會自動存在這裡")).toBeVisible();
  await expect(recent.getByRole("link")).toHaveCount(0);
  await expect(recent.getByText("看全部")).toHaveCount(0);
});

test("推薦過的比較紀錄出現在首頁，點進去到 1-3，上一步到 1-2", async ({ page }) => {
  await login(page, freshEmail("recommended"));
  await page.goto("/compare/new");
  await page.getByLabel("目的地").selectOption("日本");
  await page.getByLabel("出發日").fill(day(7));
  await page.getByLabel("回程日").fill(day(12));
  await page.getByLabel("年齡").fill("30");
  await page.getByRole("button", { name: "下一步" }).click();
  await page.getByRole("button", { name: /^班機延誤/ }).click();
  await page.getByRole("button", { name: "下一步" }).click();
  await expect(page).toHaveURL(/\/result$/);
  await page.getByRole("link", { name: "完成" }).click();

  const recent = page.getByRole("region", { name: "最近的比較" });
  const row = recent.getByRole("link");
  await expect(row).toHaveCount(1);
  await expect(row.getByText(`日本 · ${day(7).replaceAll("-", "/")} · 6 天`)).toBeVisible();
  // 「推薦 {公司} {方案名} · {保額} 萬」
  await expect(row.getByText(/^推薦 .+ · [\d,]+ 萬$/)).toBeVisible();

  await row.click();
  await expect(page).toHaveURL(/\/compare\/[0-9a-f-]{36}\/result$/);
  await page.getByRole("link", { name: "上一步" }).click();
  await expect(page).toHaveURL(/\/compare\/[0-9a-f-]{36}\/concerns$/);
});

test("只填完 1-1 的比較紀錄顯示填寫中，點進去到 1-2", async ({ page }) => {
  await login(page, freshEmail("draft"));
  await createComparison(page, "韓國", 7);
  await page.goto("/");

  const row = page.getByRole("region", { name: "最近的比較" }).getByRole("link");
  await expect(row).toHaveCount(1);
  await expect(row.getByText(`韓國 · ${day(7).replaceAll("-", "/")} · 6 天`)).toBeVisible();
  await expect(row.getByText("填寫中")).toBeVisible();

  await row.click();
  await expect(page).toHaveURL(/\/compare\/[0-9a-f-]{36}\/concerns$/);
});

test("3 筆以下不顯示看全部", async ({ page }) => {
  await login(page, freshEmail("three"));
  for (const [i, destination] of ["日本", "韓國", "泰國"].entries()) {
    await createComparison(page, destination, 7 + i);
  }
  await page.goto("/");

  const recent = page.getByRole("region", { name: "最近的比較" });
  await expect(recent.getByRole("link")).toHaveCount(3);
  await expect(recent.getByText("看全部")).toHaveCount(0);
});

test("超過 3 筆時只列前 3 筆（最近操作的在最前面），看全部 → 全部比較頁 → 回首頁", async ({
  page,
}) => {
  await login(page, freshEmail("many"));
  for (const [i, destination] of ["日本", "韓國", "泰國", "新加坡"].entries()) {
    await createComparison(page, destination, 7 + i);
  }
  await page.goto("/");

  const recent = page.getByRole("region", { name: "最近的比較" });
  // 列是帶「天數」的連結；「看全部」不算
  const rows = recent.getByRole("link", { name: /天/ });
  await expect(rows).toHaveCount(3);
  await expect(rows.nth(0)).toContainText("新加坡");
  await expect(rows.nth(2)).toContainText("韓國");

  await recent.getByRole("link", { name: "看全部" }).click();
  await expect(page).toHaveURL(/\/compare$/);
  await expect(page.getByRole("heading", { level: 1, name: "全部比較" })).toBeVisible();
  await expect(page.getByText("共 4 筆，依最後操作時間由新到舊")).toBeVisible();
  await expect(page.getByRole("link", { name: "首頁", exact: true })).toHaveAttribute("href", "/");

  // 全部 4 筆，順序與首頁一致；點列的去向與首頁相同（只填 1-1 → 1-2）
  const all = page.getByRole("main").getByRole("link", { name: /天/ });
  await expect(all).toHaveCount(4);
  await expect(all.nth(0)).toContainText("新加坡");
  await expect(all.nth(3)).toContainText("日本");
  await all.nth(3).click();
  await expect(page).toHaveURL(/\/compare\/[0-9a-f-]{36}\/concerns$/);

  await page.goto("/compare");
  await page.getByRole("link", { name: "回首頁" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("region", { name: "最近的比較" })).toBeVisible();
});

test("沒有比較紀錄時，全部比較頁顯示目前沒有紀錄", async ({ page }) => {
  await login(page, freshEmail("all-empty"));
  await page.goto("/compare");

  await expect(page.getByText("共 0 筆，依最後操作時間由新到舊")).toBeVisible();
  await expect(page.getByText("目前沒有紀錄")).toBeVisible();
});

/** 用 API 建保單與事件，回傳事件 id（需要已 make seed）。 */
async function createIncident(page: Page, description: string, policyId?: string) {
  const api = page.request;
  let id = policyId;
  if (!id) {
    const options = await (
      await api.get("/api/v1/plans/fubon_advanced/sum-insured-options")
    ).json();
    const policy = await (
      await api.post("/api/v1/policies/manual", {
        data: { plan_id: "fubon_advanced", sum_insured: options.sum_insured[0] },
      })
    ).json();
    id = policy.id as string;
  }
  const created = await api.post(`/api/v1/policies/${id}/incidents`, { data: { description } });
  expect(created.ok()).toBeTruthy();
  const body = await created.json();
  return { policyId: id, incidentId: body.incident.incident_id as string };
}

/** 把事件的待辦做完並選「自己處理」結案（做法同 incident-flow.spec.ts）。 */
async function closeIncident(page: Page, incidentId: string) {
  const api = page.request;
  for (let i = 0; i < 15; i++) {
    const reply = await (
      await api.post(`/api/v1/incidents/${incidentId}/messages`, { data: { content: "不知道" } })
    ).json();
    if (reply.reply.finished) break;
  }
  for (let i = 0; i < 20; i++) {
    const ctx = await (await api.get(`/api/v1/incidents/${incidentId}`)).json();
    const undone = ctx.todos.filter(
      (t: { is_done: boolean; status: string }) => !t.is_done && t.status !== "not_applicable",
    );
    if (undone.length === 0) break;
    if (undone[0].requires_upload) {
      await api.post(`/api/v1/incidents/${incidentId}/documents`, {
        multipart: {
          file: { name: "證明.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4") },
        },
      });
    } else {
      await api.patch(`/api/v1/incidents/${incidentId}/todos/${undone[0].id}`, {
        data: { is_done: true },
      });
    }
  }
  const submitted = await api.post(`/api/v1/incidents/${incidentId}/submission`, {
    data: { mode: "self" },
  });
  expect(submitted.ok()).toBeTruthy();
}

// 首頁右下格「我的理賠」（#207）：沒有事件的空狀態。
test("沒有事件時，我的理賠顯示空狀態", async ({ page, request }) => {
  test.skip(!(await request.get("/api/v1/plans")).ok(), "條款庫沒有載入，先 make seed");
  await login(page, freshEmail("incidents-empty"));

  const card = page.getByRole("region", { name: "我的理賠" });
  await expect(card.getByRole("heading", { name: "我的理賠" })).toBeVisible();
  await expect(card.getByText("處理過的理賠會自動存在這裡")).toBeVisible();
  await expect(card.getByTestId("incident-row-title")).toHaveCount(0);
});

// 建 4 筆事件：只列最新 3 筆，新的在前；點一列進到該事件。
test("我的理賠只列最近 3 筆，點一列進入該事件", async ({ page, request }) => {
  test.skip(!(await request.get("/api/v1/plans")).ok(), "條款庫沒有載入，先 make seed");
  await login(page, freshEmail("incidents-recent"));

  const first = await createIncident(page, "第一件：班機延誤了");
  await createIncident(page, "第二件：班機延誤了", first.policyId);
  await createIncident(page, "第三件：班機延誤了", first.policyId);
  const fourth = await createIncident(page, "第四件：班機延誤了", first.policyId);

  await page.goto("/");
  const card = page.getByRole("region", { name: "我的理賠" });
  const titles = card.getByTestId("incident-row-title");
  await expect(titles).toHaveCount(3);
  await expect(titles.nth(0)).toContainText("第四件");
  await expect(titles.nth(1)).toContainText("第三件");
  await expect(titles.nth(2)).toContainText("第二件");
  await expect(card.getByText("第一件")).toHaveCount(0);
  // 這次不做「看全部」
  await expect(card.getByRole("link", { name: "看全部" })).toHaveCount(0);
  await expect(card.getByTestId("incident-row-status").first()).toHaveText("進行中");

  await titles.nth(0).click();
  await expect(page).toHaveURL(new RegExp(`/incident/${fourth.incidentId}$`));
});

// 已結案的事件也列，並標示「已完成」。
test("已完成的事件也列在我的理賠，標示已完成", async ({ page, request }) => {
  test.skip(!(await request.get("/api/v1/plans")).ok(), "條款庫沒有載入，先 make seed");
  await login(page, freshEmail("incidents-done"));

  const done = await createIncident(page, "已結案的班機延誤");
  await closeIncident(page, done.incidentId);
  await createIncident(page, "還在處理的班機延誤", done.policyId);

  await page.goto("/");
  const rows = page.getByRole("region", { name: "我的理賠" }).getByRole("link");
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0)).toContainText("還在處理");
  await expect(rows.nth(0).getByTestId("incident-row-status")).toHaveText("進行中");
  // 結案那筆的標題不比對：e2e 用的假 5 號回覆時會自己改標題，真正的 5 號不會
  await expect(rows.nth(1).getByTestId("incident-row-status")).toHaveText("已完成");
});

// 手機寬度：我的理賠排在最近的比較下面，整頁沒有橫向捲動。
test("手機寬度下，我的理賠在最近的比較下面，沒有橫向捲動", async ({ page, request }) => {
  test.skip(!(await request.get("/api/v1/plans")).ok(), "條款庫沒有載入，先 make seed");
  await page.setViewportSize({ width: 375, height: 800 });
  await login(page, freshEmail("incidents-mobile"));
  await createIncident(page, "手機寬度的班機延誤");
  await page.goto("/");

  const comparisons = page.getByRole("region", { name: "最近的比較" });
  const incidents = page.getByRole("region", { name: "我的理賠" });
  await expect(incidents.getByTestId("incident-row-title")).toHaveCount(1);
  const above = await comparisons.boundingBox();
  const below = await incidents.boundingBox();
  expect(above && below && below.y >= above.y + above.height).toBeTruthy();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(overflow).toBe(false);
});
