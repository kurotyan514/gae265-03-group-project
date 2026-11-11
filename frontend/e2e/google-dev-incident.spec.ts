import { expect, type Page, test } from "@playwright/test";

// 事件流程測試台的 Google 授權流程（ADR-0020）。
// 用測試登入建立真的保單與事件；只攔下 /auth/me（假裝是 Google 登入）與 /auth/google/grant（授權狀態）。
// 不連 Google：只驗證「選擇檔案」與「送件」前會先確認授權、缺什麼就先請使用者授權什麼。

const SLOW = 30_000;

// 「建立範例保單」會重建大家共用的範例事件類型，同時跑會互相打亂待辦，所以這個檔案的測試依序執行
test.describe.configure({ mode: "serial" });

type Grant = { status: "none" | "active" | "invalid"; drive: boolean; gmail: boolean };

async function asGoogleUserWithIncident(page: Page, grant: Grant): Promise<void> {
  await page.goto("/login?next=%2Fdev%2Fincident");
  // 每個測試用自己的使用者，保單與事件不會和其他測試共用
  const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  await page.getByLabel("Email").fill(`e2e-google-incident-${id}@example.com`);
  await page.getByRole("button", { name: "測試登入" }).click();
  await expect(page).toHaveURL(/\/dev\/incident$/);

  // 登入後才改成 Google 使用者：其他 API 照樣用測試登入的 session
  await page.route("**/api/v1/auth/me", async (route) => {
    const response = await route.fetch();
    route.fulfill({ response, json: { ...(await response.json()), login_provider: "google" } });
  });
  await page.route("**/api/v1/auth/google/grant", (route) => route.fulfill({ json: grant }));
  await page.reload();
  await expect(page.getByTestId("dev-google-status")).toBeVisible();

  await page.getByTestId("sample-policy").click();
  await expect(page.getByTestId("policy")).not.toHaveValue("");
  await page.getByTestId("start").click();
  await expect(page.getByTestId("incident")).toBeVisible({ timeout: SLOW });
}

/** 把文件備齊：先和 5 號對話到判斷出類型，再把每一項待辦完成（和 dev-incident.spec.ts 一樣）。 */
async function completeAllTodos(page: Page): Promise<void> {
  // 5 先追問，問完才判斷出事故類型、補上該類型的待辦
  await page.getByTestId("message").fill("班機延誤了六小時");
  await page.getByTestId("send").click();
  await expect(page.getByTestId("messages").locator("li")).toHaveCount(4, {
    timeout: SLOW,
  });
  await page.getByTestId("message").fill("昨天在東京成田機場");
  await page.getByTestId("send").click();
  await expect(
    page
      .getByTestId("incident")
      .getByText(/班機延誤 ·/)
      .first(),
  ).toBeVisible({ timeout: SLOW });
  await expect(page.getByTestId("citations")).toBeVisible();
  const todos = page.getByTestId("todos").getByRole("checkbox");
  await expect(todos.first()).toBeVisible();
  const count = await todos.count();
  // 不需上傳的待辦手動勾；需上傳的會被後端擋下（409），改用上傳完成（依序處理，
  // 第一個未完成的就是這一項）。setInputFiles 不經過「選擇檔案」的點擊，所以不受 Drive 授權檢查影響
  for (let i = 0; i < count; i++) {
    const box = todos.nth(i);
    if (await box.isChecked()) continue;
    await box.click();
    try {
      await expect(box).toBeChecked({ timeout: 2000 });
    } catch {
      await page.getByTestId("doc-file").setInputFiles({
        name: "證明.pdf",
        mimeType: "application/pdf",
        buffer: Buffer.from("%PDF-1.4"),
      });
      await page.getByTestId("upload").click();
      await expect(box).toBeChecked();
    }
  }
  await expect(page.getByTestId("all-done")).toContainText("可以送件");
}

// 頁面會不時重新呼叫 /auth/me；測試結束時若還有被攔下、正在向後端拿回應的請求，先撤掉攔截並忽略，
// 否則 route.fetch 會在頁面關閉後報錯，讓已經通過的測試被判定失敗
test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: "ignoreErrors" });
});

test.beforeEach(async ({ request }) => {
  const config = await (await request.get("/api/v1/auth/config")).json();
  test.skip(!config.dev_login, "後端沒有設 DEV_LOGIN_ENABLED=true");
  test.skip(!(await request.get("/api/v1/plans")).ok(), "條款庫沒有載入，先 make seed");
});

test("沒授權 Drive：選擇檔案時不開選檔視窗，先說明 Drive 的用途", async ({ page }) => {
  await asGoogleUserWithIncident(page, { status: "none", drive: false, gmail: false });
  let chooserOpened = false;
  page.on("filechooser", () => {
    chooserOpened = true;
  });

  await page.getByTestId("doc-file").click();

  const dialog = page.getByTestId("google-consent");
  await expect(dialog).toContainText("Google Drive");
  expect(chooserOpened).toBe(false);
  // 授權完回到同一個事件
  const href = await page.getByTestId("google-consent-continue").getAttribute("href");
  expect(href).toMatch(
    /^\/api\/v1\/auth\/google\/authorize\?purpose=drive&next=%2Fdev%2Fincident%3Fincident%3D[0-9a-f-]+$/,
  );
});

test("已授權 Drive：選擇檔案直接開選檔視窗；送件時再請使用者授權 Gmail", async ({ page }) => {
  await asGoogleUserWithIncident(page, { status: "active", drive: true, gmail: false });

  const [chooser] = await Promise.all([
    page.waitForEvent("filechooser"),
    page.getByTestId("doc-file").click(),
  ]);
  expect(chooser).toBeTruthy();
  await expect(page.getByTestId("google-consent")).toHaveCount(0);

  await completeAllTodos(page);
  await page.getByTestId("submit").click();
  await expect(page.getByTestId("google-consent")).toContainText("Gmail");
  await expect(page.getByTestId("google-consent-continue")).toHaveAttribute(
    "href",
    /purpose=gmail/,
  );
});

test("文件還沒備齊、沒授權 Drive：送件時先請使用者授權 Drive，才能上傳", async ({ page }) => {
  await asGoogleUserWithIncident(page, { status: "none", drive: false, gmail: false });
  await page.getByTestId("submit").click();
  await expect(page.getByTestId("google-consent")).toContainText("Google Drive");
  await expect(page.getByTestId("google-consent-continue")).toHaveAttribute(
    "href",
    /purpose=drive/,
  );
});

test("文件還沒備齊、已授權 Drive：送件時告知還缺文件，不請求 Gmail", async ({ page }) => {
  await asGoogleUserWithIncident(page, { status: "active", drive: true, gmail: false });
  await page.getByTestId("submit").click();
  await expect(page.getByTestId("error")).toContainText("還有待辦沒完成");
  await expect(page.getByTestId("google-consent")).toHaveCount(0);
});

test("文件備齊但授權已失效：送件時先請使用者授權 Drive（寄信要讀附件）", async ({ page }) => {
  // 文件早就存進 Drive，送件時授權已經失效（setInputFiles 不經過選擇檔案的檢查，可以先把文件備齊）
  await asGoogleUserWithIncident(page, { status: "invalid", drive: false, gmail: false });
  await completeAllTodos(page);

  await page.getByTestId("submit").click();
  await expect(page.getByTestId("google-consent")).toContainText("Google Drive");
  await expect(page.getByTestId("google-consent-continue")).toHaveAttribute(
    "href",
    /purpose=drive/,
  );
});

test("授權完導回時，打開原本的事件並顯示結果", async ({ page }) => {
  await asGoogleUserWithIncident(page, { status: "none", drive: false, gmail: false });
  await page.getByTestId("doc-file").click();
  const href = await page.getByTestId("google-consent-continue").getAttribute("href");
  const next = new URLSearchParams(href?.split("?")[1]).get("next") ?? "";
  const incidentTitle = (await page.getByTestId("incident-title").textContent()) ?? "";

  // 假裝 Google 授權完、後端導回 next 並帶上結果
  await page.goto(`${next}&google_auth=granted`);
  await expect(page.getByTestId("google-auth-result")).toHaveText("已完成 Google 授權。");
  await expect(page.getByTestId("incident-title")).toHaveText(incidentTitle, { timeout: SLOW });
});
