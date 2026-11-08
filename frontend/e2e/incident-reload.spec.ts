import { expect, test } from "@playwright/test";
import { login } from "./helpers";

// 重新整理事件頁後，5 號回覆的快速選項與條文出處要還原（#212）：
// 選項只在「最後一則是 5 號的訊息」時顯示；出處跟著各自那則訊息。
// 用假 5 號：第一則附三個選項、中間一則什麼都沒附、問完那則附出處。需要已載入條款庫（make seed）。
const SLOW = 15_000;

test("重新整理後，快速選項與出處還在；答過的舊問題不再出現選項", async ({ page, request }) => {
  const config = await (await request.get("/api/v1/auth/config")).json();
  test.skip(!config.dev_login, "後端沒有設 DEV_LOGIN_ENABLED=true");
  test.skip(!(await request.get("/api/v1/plans")).ok(), "條款庫沒有載入，先 make seed");

  await login(page, `e2e-incident-reload-${Date.now()}@example.com`);

  const api = page.request;
  const options = await (await api.get("/api/v1/plans/fubon_advanced/sum-insured-options")).json();
  const policy = await (
    await api.post("/api/v1/policies/manual", {
      data: { plan_id: "fubon_advanced", sum_insured: options.sum_insured[0] },
    })
  ).json();
  const createdRes = await api.post(`/api/v1/policies/${policy.id}/incidents`, {
    data: { description: "班機延誤了六小時" },
  });
  const created = await createdRes.json();
  // 準備資料時伺服器回了錯誤：把狀態碼與內容丟出來，才看得到真正原因
  if (!created.incident)
    throw new Error(`POST incidents 回 ${createdRes.status()}：${JSON.stringify(created)}`);

  // 第一則 5 號訊息附了選項：開頁看得到，重新整理後還在
  await page.goto(`/incident/${created.incident.incident_id}`);
  const quick = page.getByTestId("quick-replies");
  await expect(quick.getByRole("button", { name: "生病受傷" })).toBeVisible({ timeout: SLOW });
  await page.reload();
  await expect(quick.getByRole("button", { name: "生病受傷" })).toBeVisible({ timeout: SLOW });

  const send = async (text: string, total: number) => {
    await page.getByTestId("message").fill(text);
    await page.getByTestId("send").click();
    await expect(page.getByTestId("messages").locator("li")).toHaveCount(total, {
      timeout: SLOW,
    });
  };

  // 旅客回答之後，最後一則 5 號訊息沒附選項：舊問題的選項不再出現，重新整理也一樣
  await send("班機延誤了六小時", 5);
  await expect(quick).toHaveCount(0);
  await page.reload();
  await expect(page.getByTestId("messages").locator("li")).toHaveCount(5, { timeout: SLOW });
  await expect(quick).toHaveCount(0);

  // 問完那則附了出處：出現在自己那則訊息底下，重新整理後還在；前面的訊息沒有
  // 問完了：畫面換成理賠頁，那裡不顯示 2-2 的開場白，所以沒有多一則
  await send("昨天在東京成田機場", 6);
  const citations = page.getByTestId("citations");
  await expect(citations).toHaveCount(1);
  await expect(citations).toContainText("依據：");
  await page.reload();
  await expect(page.getByTestId("messages").locator("li")).toHaveCount(6, { timeout: SLOW });
  await expect(citations).toHaveCount(1);
  const lastAssistant = page.getByTestId("messages").locator("li").nth(5);
  await expect(lastAssistant.getByTestId("citations")).toBeVisible();
});
