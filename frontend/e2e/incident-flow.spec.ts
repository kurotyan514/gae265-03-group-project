import { expect, type Page, test } from "@playwright/test";

const SLOW = 30_000;

// 出事了的正式流程（/incident/*）：手選方案與保額 → 說明狀況 → 待辦 → 上傳文件 → 送件。
// 用後端目前設定的 agent 實作（預設是假實作）。需要測試登入與已載入的條款庫、方案資料（make seed）。
test("出事了：手選保單後走完 說明、待辦、上傳、送件", async ({ page, request }) => {
  const config = await (await request.get("/api/v1/auth/config")).json();
  test.skip(!config.dev_login, "後端沒有設 DEV_LOGIN_ENABLED=true");
  test.skip(!(await request.get("/api/v1/plans")).ok(), "條款庫沒有載入，先 make seed");

  await page.goto("/login?next=%2F");
  await page.getByLabel("Email").fill("e2e-incident-flow@example.com");
  await page.getByRole("button", { name: "測試登入" }).click();
  await expect(page).toHaveURL(/\/$/);

  // 入口：首頁的卡片進到 /incident/new
  await page.getByRole("link", { name: /出事了：幫我處理理賠/ }).click();
  await expect(page).toHaveURL(/\/incident\/new$/);

  // 1. 沒有保單檔：自己選方案與保額
  await page.getByTestId("mode-manual").click();
  await page.getByTestId("manual-plan").selectOption("fubon_advanced");
  const sums = page.getByTestId("manual-sum-insured");
  await expect(sums.locator("option")).not.toHaveCount(1);
  await sums.selectOption({ index: 1 });
  await page.getByTestId("create-manual-policy").click();
  await expect(page.getByTestId("policy")).toContainText("富邦國外旅平險-進階型");

  // 2. 說明發生什麼事，助理先問第一個問題
  await page.getByLabel("簡單說明").fill("班機延誤了六小時");
  await page.getByTestId("start").click();
  await expect(page).toHaveURL(/\/incident\/[0-9a-f-]+$/, { timeout: SLOW });
  await expect(page.getByTestId("messages").locator("li")).toHaveCount(2, { timeout: SLOW });

  // 對話：問完才判斷出類型，補上待辦
  const reply = () =>
    page.waitForResponse((r) => r.url().endsWith("/messages") && r.request().method() === "POST", {
      timeout: SLOW,
    });
  let replied = reply();
  await page.getByTestId("message").fill("班機延誤了六小時");
  await page.getByTestId("send").click();
  await replied;
  await expect(page.getByTestId("messages").locator("li")).toHaveCount(4, { timeout: SLOW });
  replied = reply();
  await page.getByTestId("message").fill("昨天在東京成田機場");
  await page.getByTestId("send").click();
  await replied;
  await expect(page.getByTestId("todos").getByRole("checkbox").first()).toBeVisible({
    timeout: SLOW,
  });

  // 3. 上傳文件：假 6 號依檔名辨識通過並勾選待辦
  await page.getByRole("link", { name: /2\. 上傳文件/ }).click();
  await page.getByTestId("doc-file").setInputFiles({
    name: "延誤證明.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("%PDF-1.4"),
  });
  await page.getByTestId("upload").click();
  await expect(page.getByTestId("notice")).toContainText("辨識通過", { timeout: SLOW });

  // 4. 送件：待辦沒完成前不能送
  await page.getByRole("link", { name: /3\. 送件/ }).click();
  await expect(page.getByTestId("ready")).toContainText("還有");
  await expect(page.getByTestId("choose-send")).toBeDisabled();
  await expect(page.getByTestId("choose-self")).toBeDisabled();

  // 回到待辦把剩下的自己勾完，就能送件
  await page.getByRole("link", { name: /1\. 說明與待辦/ }).click();
  const boxes = page.getByTestId("todos").getByRole("checkbox");
  await expect(boxes.first()).toBeVisible();
  for (const box of await boxes.all()) {
    if (!(await box.isChecked()) && (await box.isEnabled())) {
      const patched = page.waitForResponse((r) => r.request().method() === "PATCH");
      // 勾選要等後端回應才會變，所以用 click 再等回應，不用 check()
      await box.click();
      await patched;
    }
  }
  await page.getByRole("link", { name: /3\. 送件/ }).click();
  await expect(page.getByTestId("ready")).toContainText("可以送件");

  // 先選「好險有你小助理幫我送出」：預覽信、填收件者，寄出後結案（測試登入沒有 Google 授權，不問授權）
  await page.getByTestId("choose-send").click();
  await expect(page.getByTestId("letter-body")).toBeVisible({ timeout: SLOW });
  await page.getByTestId("letter-recipient").fill("agent@example.com");
  await page.getByTestId("submit").click();
  await expect(page.getByTestId("closed")).toContainText("已用你的 Gmail 寄給保險公司", {
    timeout: SLOW,
  });

  // 結案後鎖住：不能再傳訊息或改待辦
  await expect(page.getByTestId("closed-banner")).toBeVisible();
  await page.getByRole("link", { name: /1\. 說明與待辦/ }).click();
  await expect(page.getByTestId("message")).toBeDisabled();
  await expect(page.getByTestId("send")).toBeDisabled();
  await expect(page.getByTestId("todos").getByRole("checkbox").first()).toBeDisabled();
});

/** 用 API 快速備好一個待辦全完成、可以送件的事件，回傳事件編號。 */
async function readyIncident(page: Page): Promise<string> {
  const api = page.request;
  const options = await (await api.get("/api/v1/plans/fubon_advanced/sum-insured-options")).json();
  const policy = await (
    await api.post("/api/v1/policies/manual", {
      data: { plan_id: "fubon_advanced", sum_insured: options.sum_insured[0] },
    })
  ).json();
  const created = await (
    await api.post(`/api/v1/policies/${policy.id}/incidents`, {
      data: { description: "班機延誤了六小時" },
    })
  ).json();
  const id: string = created.incident.incident_id;
  // 一直回答到 5 號問完（假 5 號最多問幾題由它決定）
  for (let i = 0; i < 15; i++) {
    const reply = await (
      await api.post(`/api/v1/incidents/${id}/messages`, { data: { content: "不知道" } })
    ).json();
    if (reply.reply.finished) break;
  }
  // 待辦全部完成：需上傳的靠假 6 號辨識，其他自己勾
  for (let i = 0; i < 20; i++) {
    const ctx = await (await api.get(`/api/v1/incidents/${id}`)).json();
    const undone = ctx.todos.filter(
      (t: { is_done: boolean; status: string }) => !t.is_done && t.status !== "not_applicable",
    );
    if (undone.length === 0) break;
    if (undone[0].requires_upload) {
      await api.post(`/api/v1/incidents/${id}/documents`, {
        multipart: {
          file: { name: "證明.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4") },
        },
      });
    } else {
      await api.patch(`/api/v1/incidents/${id}/todos/${undone[0].id}`, {
        data: { is_done: true },
      });
    }
  }

  return id;
}

// 送件的另一條路：選「我自己處理就好」、不建草稿，直接結案。事件用 API 快速備好（待辦全完成）。
test("出事了：自己處理、不建草稿，直接結案", async ({ page, request }) => {
  const config = await (await request.get("/api/v1/auth/config")).json();
  test.skip(!config.dev_login, "後端沒有設 DEV_LOGIN_ENABLED=true");
  test.skip(!(await request.get("/api/v1/plans")).ok(), "條款庫沒有載入，先 make seed");

  await page.goto("/login?next=%2F");
  await page.getByLabel("Email").fill("e2e-incident-self@example.com");
  await page.getByRole("button", { name: "測試登入" }).click();
  await expect(page).toHaveURL(/\/$/);

  const id = await readyIncident(page);

  await page.goto(`/incident/${id}/submit`);
  await expect(page.getByTestId("ready")).toContainText("可以送件", { timeout: SLOW });
  await page.getByTestId("choose-self").click();
  // 先問要不要建草稿，並說明不論選什麼都會結案；選取消就不建立
  await expect(page.getByTestId("draft-question")).toContainText("都會結案");
  await page.getByRole("button", { name: "取消" }).click();
  await expect(page.getByTestId("closed")).toContainText("沒有建立草稿", { timeout: SLOW });
  await expect(page.getByTestId("closed-banner")).toBeVisible();
});

// 寄出失敗時（7-2：附件在 Drive 的垃圾桶），說明放在預覽信那一區、寄出按鈕旁，列出是哪些附件並附上處理的入口。
// 測試登入沒有 Google 授權，用 page.route 換掉送件 API 的回應，模擬 7 號回 failed。
test("出事了：寄出失敗時在預覽信頁說明是哪些附件、怎麼處理", async ({ page, request }) => {
  const config = await (await request.get("/api/v1/auth/config")).json();
  test.skip(!config.dev_login, "後端沒有設 DEV_LOGIN_ENABLED=true");
  test.skip(!(await request.get("/api/v1/plans")).ok(), "條款庫沒有載入，先 make seed");

  await page.goto("/login?next=%2F");
  await page.getByLabel("Email").fill("e2e-incident-failed@example.com");
  await page.getByRole("button", { name: "測試登入" }).click();
  await expect(page).toHaveURL(/\/$/);
  const id = await readyIncident(page);

  // 7 號的寫法：一句說明加上一個檔案一行
  const reason = [
    "下面 2 個附件在 Google Drive 的垃圾桶裡，請到 Google Drive 的垃圾桶還原後再試一次：",
    "・班機延誤_機票及登機證_1.pdf",
    "・理賠申請書_1.pdf",
  ].join("\n");
  await page.route("**/api/v1/incidents/*/submission", (route) =>
    route.fulfill({
      status: 201,
      json: {
        id: "00000000-0000-0000-0000-000000000000",
        status: "failed",
        external_ref: null,
        reason,
      },
    }),
  );

  await page.goto(`/incident/${id}/submit`);
  await expect(page.getByTestId("ready")).toContainText("可以送件", { timeout: SLOW });
  await page.getByTestId("choose-send").click();
  await expect(page.getByTestId("letter-body")).toBeVisible({ timeout: SLOW });
  await page.getByTestId("letter-recipient").fill("agent@example.com");
  await page.getByTestId("submit").click();

  const notice = page.getByTestId("preview").getByTestId("submission");
  await expect(notice).toContainText("班機延誤_機票及登機證_1.pdf");
  // 一個檔案一行，看得出有幾個
  await expect(notice.getByTestId("submission-reason")).toHaveCSS("white-space", "pre-line");
  await expect(notice).toContainText("事件還沒結案");
  await expect(notice.getByTestId("open-drive-trash")).toHaveAttribute(
    "href",
    "https://drive.google.com/drive/trash",
  );
  // 留在預覽頁、沒有結案，可以處理後再寄一次
  await expect(page.getByTestId("submit")).toBeVisible();
  await expect(page.getByTestId("closed")).toHaveCount(0);

  // 切到「上傳文件」處理附件再回來：仍在預覽、填過的收件者還在
  await page.getByRole("link", { name: /2\. 上傳文件/ }).click();
  await expect(page).toHaveURL(/\/documents$/);
  await page.getByRole("link", { name: /3\. 送件/ }).click();
  await expect(page.getByTestId("letter-body")).toBeVisible({ timeout: SLOW });
  await expect(page.getByTestId("letter-recipient")).toHaveValue("agent@example.com");
});
