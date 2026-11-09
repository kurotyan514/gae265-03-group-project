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
  // 選好檔案就直接上傳辨識（沒有另外的「上傳」按鈕）
  await expect(page.getByTestId("upload-summary")).toContainText("1 份已自動打勾", {
    timeout: SLOW,
  });

  // 4. 送件：待辦沒完成前不能送
  // 還缺文件時 2-4 是「稍後再傳」，送件頁直接前往（網址是 /incident/<id>/documents）
  const incidentId = page.url().split("/")[4];
  await page.goto(`/incident/${incidentId}/submit`);
  await expect(page.getByTestId("ready")).toContainText("還有");
  await expect(page.getByTestId("choose-send")).toBeDisabled();
  await expect(page.getByTestId("choose-self")).toBeDisabled();

  // 回到待辦把剩下的自己勾完，就能送件
  await page.goto(`/incident/${incidentId}`);
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
  // 寄出前再確認一次：寄出後這筆理賠即結案
  await expect(page.getByTestId("send-confirm-dialog")).toContainText("即結案");
  await page.getByTestId("send-confirm").click();
  await expect(page.getByTestId("closed")).toContainText("已用你的 Gmail 寄給保險公司", {
    timeout: SLOW,
  });

  // 結案後鎖住：不能再傳訊息或改待辦
  await expect(page.getByTestId("closed-banner")).toBeVisible();
  await page.getByRole("link", { name: "回理賠頁" }).click();
  // 理賠頁：Pill 顯示已結案，問答卡換成結案說明（沒有提問列），待辦與送件區只能看
  await expect(page.getByText("已結案", { exact: true })).toBeVisible();
  await expect(page.getByTestId("closed-banner")).toContainText("只能查看");
  await expect(page.getByTestId("message")).toHaveCount(0);
  await expect(page.getByTestId("send-closed")).toBeVisible();
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
    const res = await api.post(`/api/v1/incidents/${id}/messages`, {
      data: { content: "不知道" },
    });
    const reply = await res.json();
    // 準備資料時伺服器回了錯誤：直接把狀態碼與內容丟出來，才看得到真正原因
    if (!reply.reply) throw new Error(`POST messages 回 ${res.status()}：${JSON.stringify(reply)}`);
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

  // 7 號的寫法：一句說明加上一個檔案一行；永久刪除與在垃圾桶兩種都有
  const reason = [
    "Google Drive 上找不到下面 1 個附件，請重新上傳：",
    "・理賠申請書_1.pdf",
    "下面 1 個附件在 Google Drive 的垃圾桶裡，請到 Google Drive 的垃圾桶還原後再試一次：",
    "・班機延誤_機票及登機證_1.pdf",
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
  await page.getByTestId("send-confirm").click();

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

  // 從說明的連結到「上傳文件」處理附件，再回到送件頁：仍在預覽、填過的收件者還在
  await notice.getByTestId("go-upload").click();
  await expect(page).toHaveURL(/\/documents$/);
  await page.goto(`/incident/${id}/submit`);
  await expect(page.getByTestId("letter-body")).toBeVisible({ timeout: SLOW });
  await expect(page.getByTestId("letter-recipient")).toHaveValue("agent@example.com");
});

// 契約 v2.8：預覽時 7 號在 Drive 上取不到的附件，預覽頁上方提示是哪些、怎麼處理；信裡只寫「另行提供」。
// 測試登入沒有 Google 授權，用 page.route 在預覽的回應加上一個取不到的附件。
test("出事了：預覽時提示 Drive 上取不到的附件，可以重新檢查", async ({ page, request }) => {
  const config = await (await request.get("/api/v1/auth/config")).json();
  test.skip(!config.dev_login, "後端沒有設 DEV_LOGIN_ENABLED=true");
  test.skip(!(await request.get("/api/v1/plans")).ok(), "條款庫沒有載入，先 make seed");

  await page.goto("/login?next=%2F");
  await page.getByLabel("Email").fill("e2e-incident-unavailable@example.com");
  await page.getByRole("button", { name: "測試登入" }).click();
  await expect(page).toHaveURL(/\/$/);
  const id = await readyIncident(page);

  let previews = 0;
  await page.route("**/api/v1/incidents/*/package", async (route) => {
    previews += 1;
    const response = await route.fetch();
    const pkg = await response.json();
    await route.fulfill({
      response,
      json: {
        ...pkg,
        // 需上傳的文件取不到、又沒有其他文件：7 號把那項待辦列為還缺，處理好才能寄出
        missing_todo_ids: ["00000000-0000-0000-0000-0000000000aa"],
        unavailable_attachments: [
          {
            document_id: "00000000-0000-0000-0000-000000000001",
            file_name: "班機延誤_機票及登機證_1.pdf",
            reason: "trashed",
          },
          {
            document_id: "00000000-0000-0000-0000-000000000002",
            file_name: "理賠申請書_1.pdf",
            reason: "not_found",
          },
        ],
      },
    });
  });

  await page.goto(`/incident/${id}/submit`);
  await expect(page.getByTestId("ready")).toContainText("可以送件", { timeout: SLOW });
  await page.getByTestId("choose-send").click();

  const notice = page.getByTestId("unavailable-attachments");
  await expect(notice).toContainText("下面 2 個附件在 Google Drive 上找不到");
  await expect(notice.getByTestId("unavailable-attachment")).toHaveText([
    "・班機延誤_機票及登機證_1.pdf（在垃圾桶裡）",
    "・理賠申請書_1.pdf（已刪除）",
  ]);
  await expect(notice.getByTestId("unavailable-open-trash")).toHaveAttribute(
    "href",
    "https://drive.google.com/drive/trash",
  );
  await expect(notice.getByTestId("unavailable-go-upload")).toBeVisible();
  await expect(notice).toContainText("處理好之前不能寄出。");
  await page.getByTestId("letter-recipient").fill("agent@example.com");
  await expect(page.getByTestId("submit")).toBeDisabled();

  // 到垃圾桶還原或重新上傳之後按「重新檢查」：重新讀一次預覽
  const before = previews;
  await notice.getByTestId("unavailable-recheck").click();
  await expect.poll(() => previews, { timeout: SLOW }).toBe(before + 1);
  await expect(page.getByTestId("letter-body")).toBeVisible({ timeout: SLOW });
  // 攔截的回應可能還在向後端讀資料：測試結束前停掉，避免「Test ended」的錯誤
  await page.unrouteAll({ behavior: "ignoreErrors" });
});

// 從「我自己處理就好」建立草稿時，一定要附上的文件在 Drive 上找不到：送件 API 回 409，
// 詢問頁顯示和預覽頁一樣的提示框，不顯示平台籠統的訊息。
// 測試登入不是 Google 帳號，用 page.route 模擬成 Google 登入、Drive 與 Gmail 都已授權。
test("出事了：建立草稿時必要的附件找不到，顯示和預覽頁一樣的提醒", async ({ page, request }) => {
  const config = await (await request.get("/api/v1/auth/config")).json();
  test.skip(!config.dev_login, "後端沒有設 DEV_LOGIN_ENABLED=true");
  test.skip(!(await request.get("/api/v1/plans")).ok(), "條款庫沒有載入，先 make seed");

  await page.goto("/login?next=%2F");
  await page.getByLabel("Email").fill("e2e-incident-draft-lost@example.com");
  await page.getByRole("button", { name: "測試登入" }).click();
  await expect(page).toHaveURL(/\/$/);
  const id = await readyIncident(page);

  await page.route("**/api/v1/auth/me", async (route) => {
    const response = await route.fetch();
    await route.fulfill({
      response,
      json: { ...(await response.json()), login_provider: "google" },
    });
  });
  await page.route("**/api/v1/auth/google/grant", (route) =>
    route.fulfill({ json: { status: "active", drive: true, gmail: true } }),
  );
  await page.route("**/api/v1/incidents/*/package", async (route) => {
    const response = await route.fetch();
    await route.fulfill({
      response,
      json: {
        ...(await response.json()),
        missing_todo_ids: ["00000000-0000-0000-0000-0000000000aa"],
        unavailable_attachments: [
          {
            document_id: "00000000-0000-0000-0000-000000000001",
            file_name: "理賠申請書_1.pdf",
            reason: "not_found",
          },
        ],
      },
    });
  });
  await page.route("**/api/v1/incidents/*/submission", (route) =>
    route.fulfill({ status: 409, json: { detail: "送件包還缺待辦，不能送件" } }),
  );

  await page.goto(`/incident/${id}/submit`);
  await expect(page.getByTestId("ready")).toContainText("可以送件", { timeout: SLOW });
  await page.getByTestId("choose-self").click();
  await page.getByTestId("draft-question").getByRole("button", { name: "確定" }).click();

  const notice = page.getByTestId("unavailable-attachments");
  await expect(notice).toContainText("下面 1 個附件在 Google Drive 上找不到", { timeout: SLOW });
  await expect(notice.getByTestId("unavailable-attachment")).toHaveText([
    "・理賠申請書_1.pdf（已刪除）",
  ]);
  await expect(notice).toContainText("處理好之前不能建立草稿。");
  await expect(notice.getByTestId("unavailable-go-upload")).toBeVisible();
  await expect(page.getByTestId("ready")).toContainText("處理好才能建立草稿。");
  // 不顯示平台籠統的訊息，也沒有結案
  await expect(page.getByTestId("error")).toHaveCount(0);
  await expect(page.getByTestId("closed")).toHaveCount(0);
  // 攔截的回應可能還在向後端讀資料：測試結束前停掉，避免「Test ended」的錯誤
  await page.unrouteAll({ behavior: "ignoreErrors" });
});
