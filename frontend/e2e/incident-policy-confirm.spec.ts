import path from "node:path";
import { expect, type Page, test } from "@playwright/test";

// 2-1 建立行程：上傳保單 → 表單直接填入讀到的內容並標記（讀到／讀不到）→ 改欄位 → 下一步，進到 2-2。
// 樣本是假的富邦官網 C 方案保單（20 個保單代碼，不含個資）。需要測試登入與已載入的條款庫、方案與保單代碼（make seed）。
const fixture = (name: string) => path.join(import.meta.dirname, "fixtures", name);
const POLICY_PDF = fixture("fubon-policy-c-plan.pdf");
const NEW_POLICY = "__new__";

async function loginFresh(page: Page, name: string) {
  await page.goto("/login?next=%2F");
  await page.getByLabel("Email").fill(`e2e-policy-${name}-${Date.now()}@example.com`);
  await page.getByRole("button", { name: "測試登入" }).click();
  await expect(page).toHaveURL(/\/$/);
}

test.beforeEach(async ({ request }) => {
  const config = await (await request.get("/api/v1/auth/config")).json();
  test.skip(!config.dev_login, "後端沒有設 DEV_LOGIN_ENABLED=true");
  test.skip(!(await request.get("/api/v1/plans")).ok(), "條款庫沒有載入，先 make seed");
});

test("上傳保單後表單填入讀到的內容並標記，可修改欄位，下一步到 2-2", async ({ page }) => {
  await loginFresh(page, "upload");

  await page.goto("/incident/new");
  await page.getByTestId("mode-upload").click();
  await page.getByTestId("policy-file").setInputFiles(POLICY_PDF);

  // 沒填完整時不能下一步；上傳後讀到的欄位填入並標記
  const form = page.getByTestId("trip-form");
  await expect(page.getByText("📎 fubon-policy-c-plan.pdf · 已讀取")).toBeVisible();
  await expect(form.getByTestId("confirm-company")).toHaveValue("富邦產物");
  await expect(form.getByTestId("confirm-plan").locator("option:checked")).toContainText(
    "官網C方案",
  );
  // 公司與方案由保單決定，上傳後不能改
  await expect(form.getByTestId("confirm-company")).toBeDisabled();
  await expect(form.getByTestId("confirm-plan")).toBeDisabled();
  // 唯讀的商品名稱、險種與附加條款
  await expect(form.getByTestId("confirm-product-name")).toContainText("115.04版");
  await expect(form.getByTestId("confirm-insurances")).toContainText("旅行平安保險");
  await expect(form.getByTestId("confirm-riders")).toContainText("班機延誤理賠文件簡化附加條款");
  // 保單專用方案沒有報價，保額要能自己輸入，不是只有一個選項的下拉
  await expect(form.getByTestId("confirm-sum-insured")).toHaveValue("6000000");
  await expect(form.getByTestId("confirm-sum-insured")).toHaveAttribute("type", "number");
  await expect(form.getByTestId("confirm-destination")).toHaveValue("日本");
  await expect(form.getByTestId("confirm-start-date")).toHaveValue(/2026-05-28/);
  await expect(form.getByTestId("confirm-start-time")).toHaveValue("09:00");
  await expect(form.getByTestId("confirm-end-time")).toHaveValue("09:00");
  for (const key of ["sum_insured", "destination", "period"]) {
    await expect(form.getByTestId(`mark-${key}`)).toContainText("由保單自動帶入");
  }

  // 改目的地：該欄的標記消失，其他欄位不受影響
  await form.getByTestId("confirm-destination").fill("日本、韓國");
  await expect(form.getByTestId("mark-destination")).toHaveCount(0);
  await expect(form.getByTestId("mark-sum_insured")).toBeVisible();

  // 只改結束日：期間的標記消失；沒動的時間不會被改到（存回後結束時間仍是 09:00）
  await form.getByTestId("confirm-end-date").fill("2026-06-06");
  await expect(form.getByTestId("mark-period")).toHaveCount(0);

  // 結束日早於開始日：顯示錯誤、不能下一步
  await form.getByTestId("confirm-end-date").fill("2026-05-01");
  await expect(form.getByTestId("period-error")).toContainText("結束日不能早於開始日");
  await expect(form.getByTestId("confirm-continue")).toBeDisabled();
  await form.getByTestId("confirm-end-date").fill("2026-06-06");
  await expect(form.getByTestId("period-error")).toHaveCount(0);

  // 下一步：存檔、Toast、到 2-2；2-2 不再問目的地
  await form.getByTestId("confirm-continue").click();
  await expect(page).toHaveURL(/\/incident\/new\/[0-9a-f-]{36}$/);
  await expect(page.getByTestId("start-form")).toBeVisible();
  await expect(page.getByLabel("目的地")).toHaveCount(0);
  const policies = await (await page.request.get("/api/v1/policies")).json();
  const saved = policies.find((p: { plan_name: string }) => p.plan_name.includes("官網C方案"));
  expect(saved.destination).toBe("日本、韓國");
  expect(saved.sum_insured).toBe(6_000_000);
  expect(saved.end_date).toBe("2026-06-06");
  expect(saved.end_at).toMatch(/^2026-06-06T09:00:00\+08:00$/);
  expect(saved.start_at).toMatch(/^2026-05-28T09:00:00\+08:00$/);
});

// 有報價的方案（富邦進階型）：保額是下拉；保單上沒印旅遊國家：目的地標「讀不到」，自己填後標記消失才能下一步。
test("有報價的方案用保額下拉，讀不到的欄位標示請自行選擇，填完才能下一步", async ({ page }) => {
  await loginFresh(page, "advanced");

  await page.goto("/incident/new");
  await page.getByTestId("mode-upload").click();
  await page
    .getByTestId("policy-file")
    .setInputFiles(fixture("fubon-policy-advanced-no-country.pdf"));

  const form = page.getByTestId("trip-form");
  await expect(form.getByTestId("confirm-plan").locator("option:checked")).toContainText("進階型");
  // 保單上讀到 6,000,000，不一定在報價裡，仍要留在選項中，並且有其他報價可選
  const sum = form.getByTestId("confirm-sum-insured");
  await expect(sum).toHaveJSProperty("tagName", "SELECT");
  await expect(sum).toHaveValue("6000000");
  expect(await sum.locator("option").count()).toBeGreaterThan(1);
  // 改選別的報價之後，保單上讀到的保額還在選項裡，可以選回來
  await sum.selectOption({ index: 1 });
  await sum.selectOption("6000000");
  await expect(sum).toHaveValue("6000000");

  // 目的地讀不到：標記，而且沒填之前不能下一步
  await expect(form.getByTestId("mark-destination")).toContainText("保單上讀不到");
  await expect(form.getByTestId("confirm-continue")).toBeDisabled();
  await form.getByTestId("confirm-destination").fill("日本");
  await expect(form.getByTestId("mark-destination")).toHaveCount(0);
  await expect(form.getByTestId("confirm-continue")).toBeEnabled();

  await form.getByTestId("confirm-continue").click();
  await expect(page.getByTestId("start-form")).toBeVisible();
});

// 「我的保單」：改選既有保單，欄位預填那份保單的內容；2-2 的「上一步」回來還是同一份保單。
test("改選我的保單時欄位預填，從 2-2 上一步回來仍是同一份保單，開出的事件用保單的目的地", async ({
  page,
}) => {
  await loginFresh(page, "existing");
  const api = page.request;

  // 第一份：官網 C 方案，保單上的目的地是日本
  await page.goto("/incident/new");
  await page.getByTestId("mode-upload").click();
  await page.getByTestId("policy-file").setInputFiles(POLICY_PDF);
  await page.getByTestId("confirm-continue").click();
  await expect(page.getByTestId("start-form")).toBeVisible();

  // 第二份：進階型，保單沒印旅遊國家，確認時自己填韓國
  await page.goto("/incident/new");
  await page.getByTestId("policy").selectOption(NEW_POLICY);
  await page.getByTestId("mode-upload").click();
  await page
    .getByTestId("policy-file")
    .setInputFiles(fixture("fubon-policy-advanced-no-country.pdf"));
  // 上傳是非同步的，讀完後表單才會填入保單的值；要等「已讀取」出現再填，不然會被蓋掉
  await expect(page.getByText("📎 fubon-policy-advanced-no-country.pdf · 已讀取")).toBeVisible();
  await page.getByTestId("confirm-destination").fill("韓國");
  await page.getByTestId("confirm-continue").click();
  await expect(page.getByTestId("start-form")).toBeVisible();

  // 2-2 按上一步：回到 2-1，剛才那份（進階型）已選好，欄位是它的內容
  await page.getByRole("link", { name: "上一步" }).click();
  await expect(page).toHaveURL(/\/incident\/new\?policy=[0-9a-f-]{36}$/);
  const form = page.getByTestId("trip-form");
  await expect(form.getByTestId("confirm-destination")).toHaveValue("韓國");
  await expect(form.getByTestId("confirm-plan").locator("option:checked")).toContainText("進階型");

  // 改選第一份（官網 C 方案）：欄位換成日本；再選回第二份：換回韓國
  const select = form.getByTestId("policy");
  const cPlan = await select
    .locator("option", { hasText: "官網C方案" })
    .first()
    .getAttribute("value");
  const advanced = await select
    .locator("option", { hasText: "進階型" })
    .first()
    .getAttribute("value");
  if (!cPlan || !advanced) throw new Error("找不到保單選項");
  await select.selectOption(cPlan);
  await expect(form.getByTestId("confirm-destination")).toHaveValue("日本");
  await select.selectOption(advanced);
  await expect(form.getByTestId("confirm-destination")).toHaveValue("韓國");

  // 選回第一份直接下一步，說明後開出的事件，目的地就是日本
  await select.selectOption(cPlan);
  await form.getByTestId("confirm-continue").click();
  await page.getByLabel("簡單說明").fill("班機延誤了六小時");
  await page.getByTestId("start").click();
  await expect(page).toHaveURL(/\/incident\/[0-9a-f-]+$/);
  const id = page.url().split("/").pop();
  const incident = await (await api.get(`/api/v1/incidents/${id}`)).json();
  expect(incident.destination).toBe("日本");
});
