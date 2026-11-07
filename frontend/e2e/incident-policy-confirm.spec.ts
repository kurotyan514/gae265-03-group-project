import path from "node:path";
import { expect, test } from "@playwright/test";

// 上傳保單 → 確認卡（看到讀到的內容與標記）→ 改一個欄位 → 按「確認，繼續」進到說明頁，目的地已預填。
// 樣本是假的富邦官網 C 方案保單（20 個保單代碼，不含個資）。需要測試登入與已載入的條款庫、方案與保單代碼（make seed）。
const fixture = (name: string) => path.join(import.meta.dirname, "fixtures", name);
const POLICY_PDF = fixture("fubon-policy-c-plan.pdf");

test("上傳保單後出現確認卡，可修改欄位並帶到說明頁", async ({ page, request }) => {
  const config = await (await request.get("/api/v1/auth/config")).json();
  test.skip(!config.dev_login, "後端沒有設 DEV_LOGIN_ENABLED=true");
  test.skip(!(await request.get("/api/v1/plans")).ok(), "條款庫沒有載入，先 make seed");

  await page.goto("/login?next=%2F");
  await page.getByLabel("Email").fill("e2e-policy-confirm@example.com");
  await page.getByRole("button", { name: "測試登入" }).click();
  await expect(page).toHaveURL(/\/$/);

  await page.goto("/incident/new");
  await page.getByTestId("mode-upload").click();
  await page.getByTestId("policy-file").setInputFiles(POLICY_PDF);
  await page.getByTestId("upload-policy").click();

  // 確認卡：唯讀的公司、方案、商品名稱、險種與附加條款
  const card = page.getByTestId("confirm-card");
  await expect(card).toBeVisible();
  await expect(card.getByTestId("confirm-company")).toHaveText("富邦產物");
  await expect(card.getByTestId("confirm-plan")).toContainText("官網C方案");
  await expect(card.getByTestId("confirm-product-name")).toContainText("115.04版");
  await expect(card.getByTestId("confirm-insurances")).toContainText("旅行平安保險");
  await expect(card.getByTestId("confirm-riders")).toContainText("班機延誤理賠文件簡化附加條款");
  // 讀到的欄位帶入並標記
  await expect(card.getByTestId("confirm-sum-insured")).toHaveValue("6000000");
  // 保單專用方案沒有報價，保額要能自己輸入，不是只有一個選項的下拉
  await expect(card.getByTestId("confirm-sum-insured")).toHaveAttribute("type", "number");
  await expect(card.getByTestId("confirm-destination")).toHaveValue("日本");
  await expect(card.getByTestId("confirm-start-date")).toHaveValue(/2026-05-28/);
  await expect(card.getByTestId("confirm-start-time")).toHaveValue("09:00");
  await expect(card.getByTestId("confirm-end-time")).toHaveValue("09:00");
  for (const key of ["sum_insured", "destination", "period"]) {
    await expect(card.getByTestId(`mark-${key}`)).toContainText("由保單自動帶入");
  }

  // 改目的地：該欄的標記消失，其他欄位不受影響
  await card.getByTestId("confirm-destination").fill("日本、韓國");
  await expect(card.getByTestId("mark-destination")).toHaveCount(0);
  await expect(card.getByTestId("mark-sum_insured")).toBeVisible();

  // 只改結束日：期間的標記消失；沒動的時間不會被改到（存回後結束時間仍是 09:00）
  await card.getByTestId("confirm-end-date").fill("2026-06-06");
  await expect(card.getByTestId("mark-period")).toHaveCount(0);

  // 確認：回到說明頁，保單已選好，目的地預填，修改存進後端
  await card.getByTestId("confirm-continue").click();
  await expect(page.getByTestId("start-form")).toBeVisible();
  await expect(page.getByTestId("confirm-card")).toHaveCount(0);
  await expect(page.getByTestId("policy")).toContainText("官網C方案");
  await expect(page.getByLabel("目的地（選填）")).toHaveValue("日本、韓國");
  // 清單新的在前；同一個帳號重跑會累積保單，所以找最新的官網 C 方案那份
  const policies = await (await page.request.get("/api/v1/policies")).json();
  const saved = policies.find((p: { plan_name: string }) => p.plan_name.includes("官網C方案"));
  expect(saved.destination).toBe("日本、韓國");
  expect(saved.sum_insured).toBe(6_000_000);
  expect(saved.end_date).toBe("2026-06-06");
  expect(saved.end_at).toMatch(/^2026-06-06T09:00:00\+08:00$/);
  expect(saved.start_at).toMatch(/^2026-05-28T09:00:00\+08:00$/);
});

// 有報價的方案（富邦進階型）：保額是下拉；保單上沒印旅遊國家：目的地標「讀不到」，自己填後標記消失。
test("有報價的方案用保額下拉，讀不到的欄位標示請自行填寫", async ({ page, request }) => {
  const config = await (await request.get("/api/v1/auth/config")).json();
  test.skip(!config.dev_login, "後端沒有設 DEV_LOGIN_ENABLED=true");
  test.skip(!(await request.get("/api/v1/plans")).ok(), "條款庫沒有載入，先 make seed");

  await page.goto("/login?next=%2F");
  await page.getByLabel("Email").fill("e2e-policy-confirm-2@example.com");
  await page.getByRole("button", { name: "測試登入" }).click();
  await expect(page).toHaveURL(/\/$/);

  await page.goto("/incident/new");
  await page.getByTestId("mode-upload").click();
  await page
    .getByTestId("policy-file")
    .setInputFiles(fixture("fubon-policy-advanced-no-country.pdf"));
  await page.getByTestId("upload-policy").click();

  const card = page.getByTestId("confirm-card");
  await expect(card.getByTestId("confirm-plan")).toContainText("進階型");
  // 保單上讀到 6,000,000，不一定在報價裡，仍要留在選項中，並且有其他報價可選
  const sum = card.getByTestId("confirm-sum-insured");
  await expect(sum).toHaveJSProperty("tagName", "SELECT");
  await expect(sum).toHaveValue("6000000");
  expect(await sum.locator("option").count()).toBeGreaterThan(1);
  // 改選別的報價之後，保單上讀到的保額還在選項裡，可以選回來
  await sum.selectOption({ index: 1 });
  await sum.selectOption("6000000");
  await expect(sum).toHaveValue("6000000");

  await expect(card.getByTestId("mark-destination")).toContainText("保單上讀不到");
  await card.getByTestId("confirm-destination").fill("日本");
  await expect(card.getByTestId("mark-destination")).toHaveCount(0);

  await card.getByTestId("confirm-continue").click();
  await expect(page.getByTestId("start-form")).toBeVisible();
  await expect(page.getByLabel("目的地（選填）")).toHaveValue("日本");
});
