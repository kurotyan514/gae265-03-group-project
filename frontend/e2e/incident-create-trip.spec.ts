import { expect, type Page, test } from "@playwright/test";
import { login } from "./helpers";

// 2-1 建立行程（/incident/new）：手動選擇的必填順序、手機版、頁底的「我的理賠」清單。需要 make seed。
async function loginFresh(page: Page, name: string) {
  await login(page, `e2e-trip-${name}-${Date.now()}@example.com`);
}

test.beforeEach(async ({ request }) => {
  const config = await (await request.get("/api/v1/auth/config")).json();
  test.skip(!config.dev_login, "後端沒有設 DEV_LOGIN_ENABLED=true");
  test.skip(!(await request.get("/api/v1/plans")).ok(), "條款庫沒有載入，先 make seed");
});

test("手動選擇：公司、方案、保額、目的地、期間都填了才能下一步，方案依公司連動", async ({
  page,
}) => {
  await loginFresh(page, "manual");
  await page.goto("/incident/new");
  await page.getByTestId("mode-manual").click();

  const next = page.getByTestId("confirm-continue");
  const plan = page.getByTestId("confirm-plan");
  const sum = page.getByTestId("confirm-sum-insured");
  await expect(next).toBeDisabled();
  // 沒選公司前，方案與保額都不能選
  await expect(plan).toBeDisabled();
  await expect(plan.locator("option:checked")).toHaveText("先選保險公司");
  await expect(sum).toBeDisabled();

  await page.getByTestId("confirm-company").selectOption("富邦產物");
  await expect(plan).toBeEnabled();
  // 方案只列這家公司的
  const names = await plan.locator("option").allTextContents();
  expect(names.some((n) => n.includes("富邦"))).toBeTruthy();
  expect(names.some((n) => n.includes("安達"))).toBeFalsy();
  await plan.selectOption("fubon_advanced");
  await expect(sum.locator("option")).not.toHaveCount(1);
  await sum.selectOption({ index: 1 });
  await expect(next).toBeDisabled(); // 還差目的地與期間
  await page.getByTestId("confirm-destination").fill("日本");
  await expect(next).toBeDisabled();
  await page.getByLabel("開始日").fill("2026-12-01");
  await page.getByLabel("結束日").fill("2026-12-05");
  await expect(next).toBeEnabled();

  // 換公司：方案與保額要重選，下一步又不能按
  await page.getByTestId("confirm-company").selectOption("安達產物");
  await expect(plan.locator("option:checked")).toHaveText("請選擇");
  await expect(next).toBeDisabled();
});

test("手機寬度（390px）下 2-1 單欄、沒有橫向捲動", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await loginFresh(page, "mobile");
  await page.goto("/incident/new");
  await page.getByTestId("mode-manual").click();
  await expect(page.getByTestId("trip-form")).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(overflow).toBe(false);
  // 公司與方案兩欄在手機上上下排
  const company = await page.getByTestId("confirm-company").boundingBox();
  const plan = await page.getByTestId("confirm-plan").boundingBox();
  expect(company && plan && plan.y > company.y + company.height - 1).toBeTruthy();
});

test("頁底的「我的理賠」列出事件，點一列進入該事件", async ({ page }) => {
  await loginFresh(page, "list");
  const api = page.request;
  const options = await (await api.get("/api/v1/plans/fubon_advanced/sum-insured-options")).json();
  const policy = await (
    await api.post("/api/v1/policies/manual", {
      data: { plan_id: "fubon_advanced", sum_insured: options.sum_insured[0] },
    })
  ).json();
  const created = await (
    await api.post(`/api/v1/policies/${policy.id}/incidents`, {
      data: { description: "班機延誤了" },
    })
  ).json();

  await page.goto("/incident/new");
  const list = page.getByTestId("incidents");
  await expect(list.getByTestId("incident-row-title")).toHaveCount(1);
  await list.getByTestId("incident-row-title").click();
  await expect(page).toHaveURL(new RegExp(`/incident/${created.incident.incident_id}$`));
});
