import { expect, test } from "@playwright/test";

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

  // 1. 沒有保單檔：手動選擇公司、方案、保額、目的地與保險期間（這個帳號重跑會累積保單，所以先切到「建立新的」）
  // 「我的保單」選單是非同步載入的，所以先問 API 有沒有保單，有才等選單出現再切
  const saved = await (await page.request.get("/api/v1/policies")).json();
  if (saved.length > 0) await page.getByTestId("policy").selectOption("__new__");
  await page.getByTestId("mode-manual").click();
  await page.getByTestId("confirm-company").selectOption("富邦產物");
  await page.getByTestId("confirm-plan").selectOption("fubon_advanced");
  const sums = page.getByTestId("confirm-sum-insured");
  await expect(sums.locator("option")).not.toHaveCount(1);
  await sums.selectOption({ index: 1 });
  await page.getByTestId("confirm-destination").fill("日本");
  await page.getByLabel("開始日").fill("2026-12-01");
  await page.getByLabel("結束日").fill("2026-12-05");
  await page.getByTestId("confirm-continue").click();

  // 2. 說明發生什麼事，助理先問第一個問題
  await expect(page).toHaveURL(/\/incident\/new\/[0-9a-f-]{36}$/);
  await page.getByTestId("message").fill("班機延誤了六小時");
  await page.getByTestId("send").click();
  await expect(page).toHaveURL(/\/incident\/[0-9a-f-]+$/, { timeout: SLOW });
  // 開場白、旅客的第一句、5 號的第一個追問
  await expect(page.getByTestId("messages").locator("li")).toHaveCount(3, { timeout: SLOW });

  // 對話：問完才判斷出類型，補上待辦
  const reply = () =>
    page.waitForResponse((r) => r.url().endsWith("/messages") && r.request().method() === "POST", {
      timeout: SLOW,
    });
  let replied = reply();
  await page.getByTestId("message").fill("班機延誤了六小時");
  await page.getByTestId("send").click();
  await replied;
  await expect(page.getByTestId("messages").locator("li")).toHaveCount(5, { timeout: SLOW });
  replied = reply();
  await page.getByTestId("message").fill("昨天在東京成田機場");
  await page.getByTestId("send").click();
  await replied;
  await expect(page.getByTestId("todos").getByRole("checkbox").first()).toBeVisible({
    timeout: SLOW,
  });

  // 3. 上傳文件：假 6 號依檔名辨識通過並勾選待辦
  await page.getByRole("link", { name: "上傳理賠文件" }).click();
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
      // 需上傳但還沒有文件的待辦，勾之前會先確認（會標「未附文件」）
      const confirm = page.getByTestId("tick-confirm");
      if (await confirm.isVisible()) await confirm.click();
      await patched;
    }
  }
  // 理賠頁沒有舊的步驟列：待辦都完成後，送件區出現「文件已備齊」與「送件」
  await expect(page.getByTestId("send-box")).toContainText("文件已備齊");
  await page.getByTestId("go-submit").click();
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
  // 理賠頁：Pill 顯示已結案，問答卡換成結案說明（沒有提問列），待辦與送件區只能看
  await expect(page.getByText("已結案", { exact: true })).toBeVisible();
  await expect(page.getByTestId("closed-banner")).toContainText("只能查看");
  await expect(page.getByTestId("message")).toHaveCount(0);
  await expect(page.getByTestId("send-closed")).toBeVisible();
  await expect(page.getByTestId("todos").getByRole("checkbox").first()).toBeDisabled();
});

// 送件的另一條路：選「我自己處理就好」、不建草稿，直接結案。事件用 API 快速備好（待辦全完成）。
test("出事了：自己處理、不建草稿，直接結案", async ({ page, request }) => {
  const config = await (await request.get("/api/v1/auth/config")).json();
  test.skip(!config.dev_login, "後端沒有設 DEV_LOGIN_ENABLED=true");
  test.skip(!(await request.get("/api/v1/plans")).ok(), "條款庫沒有載入，先 make seed");

  await page.goto("/login?next=%2F");
  await page.getByLabel("Email").fill("e2e-incident-self@example.com");
  await page.getByRole("button", { name: "測試登入" }).click();
  await expect(page).toHaveURL(/\/$/);

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

  await page.goto(`/incident/${id}/submit`);
  await expect(page.getByTestId("ready")).toContainText("可以送件", { timeout: SLOW });
  await page.getByTestId("choose-self").click();
  // 先問要不要建草稿，並說明不論選什麼都會結案；選取消就不建立
  await expect(page.getByTestId("draft-question")).toContainText("都會結案");
  await page.getByRole("button", { name: "取消" }).click();
  await expect(page.getByTestId("closed")).toContainText("沒有建立草稿", { timeout: SLOW });
  await expect(page.getByTestId("closed-banner")).toBeVisible();
});
