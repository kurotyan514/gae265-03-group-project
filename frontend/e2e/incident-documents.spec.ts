import { expect, type Page, test } from "@playwright/test";

// 2-4 上傳理賠文件（/incident/$id/documents）：還缺的文件、選檔即上傳、辨識結果、返回與送件動作。
// 用假 6 號：依檔名辨識（含「延誤證明」之類關鍵字通過，認不出來的是需要你確認）。需要 make seed。
const SLOW = 15_000;
const pdf = (name: string) => ({
  name,
  mimeType: "application/pdf",
  buffer: Buffer.from("%PDF-1.4"),
});

async function setup(page: Page, name: string) {
  await page.goto("/login?next=%2F");
  await page.getByLabel("Email").fill(`e2e-docs-${name}-${Date.now()}@example.com`);
  await page.getByRole("button", { name: "測試登入" }).click();
  await expect(page).toHaveURL(/\/$/);
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
  const created = await (
    await api.post(`/api/v1/policies/${policy.id}/incidents`, {
      data: { description: "班機延誤了六小時" },
    })
  ).json();
  const id: string = created.incident.incident_id;
  for (let i = 0; i < 15; i++) {
    const reply = await (
      await api.post(`/api/v1/incidents/${id}/messages`, { data: { content: "不知道" } })
    ).json();
    if (reply.reply.finished) break;
  }
  return id;
}

test.beforeEach(async ({ request }) => {
  const config = await (await request.get("/api/v1/auth/config")).json();
  test.skip(!config.dev_login, "後端沒有設 DEV_LOGIN_ENABLED=true");
  test.skip(!(await request.get("/api/v1/plans")).ok(), "條款庫沒有載入，先 make seed");
});

test("還缺的文件依事故與整個行程分組；頁首沿用行程資訊，沒有舊的步驟列", async ({ page }) => {
  const id = await setup(page, "missing");
  await page.goto(`/incident/${id}/documents`);

  await expect(page.getByRole("heading", { level: 1 })).toHaveText("上傳理賠文件");
  await expect(page.getByText("日本 2026/07/05～07/10 · 富邦國外旅平險-進階型")).toBeVisible();
  await expect(page.getByRole("navigation", { name: "理賠步驟" })).toHaveCount(0);
  const missing = page.getByTestId("open-todos");
  await expect(missing.getByRole("heading", { name: /班機延誤/ })).toBeVisible();
  await expect(missing.getByRole("heading", { name: "整個行程" })).toBeVisible();
  await expect(missing.getByText("填寫理賠申請書")).toBeVisible();
  await expect(page.getByText(/^\d+ 份$/)).toBeVisible();
  // 還缺文件：動作列是「稍後再傳」；提醒信範本是反灰按鈕
  await expect(page.getByRole("link", { name: "回理賠頁" })).toBeVisible();
  await expect(page.getByTestId("upload-later")).toBeVisible();
  await expect(page.getByTestId("go-submit")).toHaveCount(0);
  await page.getByRole("button", { name: "看提醒信範本" }).click({ force: true });
  await expect(page.getByTestId("toast")).toHaveText("暫無作用");
});

test("選好檔案就上傳辨識，可一次選多份，結果列在辨識結果卡", async ({ page }) => {
  const id = await setup(page, "upload");
  await page.goto(`/incident/${id}/documents`);
  await expect(page.getByTestId("documents")).toHaveCount(0); // 上傳前沒有結果卡

  const missingBefore = Number(
    (await page.getByText(/^\d+ 份$/).textContent())?.replace(/\D/g, ""),
  );
  await page.getByTestId("doc-file").setInputFiles([pdf("延誤證明.pdf"), pdf("機票與登機證.pdf")]);
  // 上傳回應是一份一條訊息；系統會把檔案依「事故類型_待辦名稱_序號」改名，認不出來的叫 unmatched_N，
  // 所以不比對原檔名，只看有兩條、其中一份辨識通過
  const notice = page.getByTestId("notice");
  await expect(notice).toContainText("辨識通過", { timeout: SLOW });
  await expect(notice.locator("p")).toHaveCount(2);
  // 結果卡：每份檔案一列
  await expect(page.getByTestId("documents").locator("li")).toHaveCount(2);
  await expect(page.getByTestId("documents")).toContainText("辨識通過");
  // 通過的文件勾起了待辦，還缺的份數減少
  const text = await page.getByText(/^\d+ 份$/).textContent();
  expect(Number(text?.replace(/\D/g, ""))).toBeLessThan(missingBefore);
});

test("無法辨識的文件：選對應的待辦後確認", async ({ page }) => {
  const id = await setup(page, "review");
  await page.goto(`/incident/${id}/documents`);

  await page.getByTestId("doc-file").setInputFiles(pdf("隨便一份.pdf"));
  const row = page.getByTestId("documents").locator("li").first();
  await expect(row).toContainText("無法辨識", { timeout: SLOW });
  const confirm = row.getByRole("button", { name: "確認是這份文件" });
  await expect(confirm).toBeDisabled();
  await row.getByRole("combobox").selectOption({ index: 1 });
  await confirm.click();
  await expect(row).toContainText("你已確認");
});

test("稍後再傳回到理賠頁並提示；需上傳的文件都備齊後出現「去送件」", async ({ page }) => {
  const id = await setup(page, "later");
  await page.goto(`/incident/${id}/documents`);
  await page.getByTestId("upload-later").click();
  await expect(page).toHaveURL(new RegExp(`/incident/${id}$`));
  await expect(page.getByTestId("toast")).toContainText("補傳");

  // 把需上傳的待辦都處理掉（自己勾，標未附文件）：2-4 顯示備齊與「去送件」
  const ctx = await (await page.request.get(`/api/v1/incidents/${id}`)).json();
  for (const t of ctx.todos.filter((x: { requires_upload: boolean }) => x.requires_upload)) {
    await page.request.patch(`/api/v1/incidents/${id}/todos/${t.id}`, { data: { is_done: true } });
  }
  await page.goto(`/incident/${id}/documents`);
  await expect(page.getByTestId("open-todos-empty")).toContainText("都已備齊");
  await page.getByTestId("go-submit").click();
  await expect(page).toHaveURL(new RegExp(`/incident/${id}/submit$`));
});

test("手機寬度（390px）下 2-4 沒有橫向捲動，動作列兩欄", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  const id = await setup(page, "mobile");
  await page.goto(`/incident/${id}/documents`);
  await expect(page.getByTestId("open-todos")).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(overflow).toBe(false);
  // 手機上主要按鈕移到動作列最上面
  const primary = await page.getByTestId("upload-later").boundingBox();
  const back = await page.getByRole("link", { name: "回理賠頁" }).boundingBox();
  expect(primary && back && primary.y < back.y).toBeTruthy();
});
