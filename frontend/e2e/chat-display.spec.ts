import { expect, type Page, test } from "@playwright/test";

// 不依賴後端與 LLM：攔下 API，固定回答的各種樣子。
const CID = "00000000-0000-0000-0000-0000000000c1";
const CITATION = {
  rule_id: "00000000-0000-0000-0000-0000000000e1",
  insurance_code: "TAIAN01",
  insurance_name: "泰安產物旅行平安保險",
  article_no: 12,
  title: "保險事故的通知",
  section: null,
  page_start: 5,
  page_end: 5,
  excerpt: "應於知悉後通知本公司。",
  score: 0.5,
};

type Reply = { content: string; original_only: boolean; citations: unknown[] };

type Result = Reply | number;

async function setup(page: Page, reply: Result | (() => Result | Promise<Result>)) {
  await page.route("**/api/v1/auth/me", (r) =>
    r.fulfill({ json: { id: "u1", email: "a@example.com", name: null } }),
  );
  const history: unknown[] = [];
  await page.route(`**/api/v1/conversations/${CID}/messages`, async (route) => {
    if (route.request().method() === "GET") return route.fulfill({ json: history });
    const out = typeof reply === "function" ? await reply() : reply;
    if (typeof out === "number") return route.fulfill({ status: out, json: { detail: "boom" } });
    const body = {
      id: "m2",
      seq: 2,
      role: "assistant",
      created_at: "2026-11-03T00:00:00Z",
      ...out,
    };
    history.push(
      {
        id: "m1",
        seq: 1,
        role: "user",
        content: route.request().postDataJSON().content,
        original_only: false,
        created_at: "2026-11-03T00:00:00Z",
        citations: [],
      },
      body,
    );
    return route.fulfill({ json: body });
  });
  await page.goto(`/chat/${CID}`);
}

async function ask(page: Page, text: string) {
  await page.getByLabel("提問").fill(text);
  await page.getByRole("button", { name: "送出" }).click();
}

test("保單沒載明的內容顯示「保單未載明」，沒有出處", async ({ page }) => {
  await setup(page, {
    content: "保單未載明，請向保險公司確認",
    original_only: false,
    citations: [],
  });
  await ask(page, "可以帶寵物嗎？");
  await expect(page.getByTestId("assistant-content")).toHaveText("保單未載明，請向保險公司確認");
  await expect(page.getByTestId("citation")).toHaveCount(0);
});

test("退回只顯示原文時標示出來", async ({ page }) => {
  await setup(page, {
    content: "（無法產生白話說明，以下直接列出條款原文。）\n\n應於知悉後通知本公司。",
    original_only: true,
    citations: [CITATION],
  });
  await ask(page, "怎麼申請");
  await expect(page.getByTestId("original-only-badge")).toContainText("條款原文");
  await expect(page.getByTestId("citation")).toContainText("第 12 條");
});

test("白話說明不顯示原文標記", async ({ page }) => {
  await setup(page, {
    content: "請盡快通知保險公司。",
    original_only: false,
    citations: [CITATION],
  });
  await ask(page, "怎麼申請");
  await expect(page.getByTestId("assistant-content")).toHaveText("請盡快通知保險公司。");
  await expect(page.getByTestId("original-only-badge")).toHaveCount(0);
});

test("送出失敗保留問題並可重試", async ({ page }) => {
  let calls = 0;
  await setup(page, () =>
    ++calls === 1
      ? 500
      : { content: "請盡快通知保險公司。", original_only: false, citations: [CITATION] },
  );
  await ask(page, "怎麼申請");
  await expect(page.getByRole("alert")).toContainText("送出失敗");
  await expect(page.getByLabel("提問")).toHaveValue("怎麼申請");

  await page.getByRole("button", { name: "重試" }).click();
  await expect(page.getByTestId("assistant-content")).toHaveText("請盡快通知保險公司。");
  await expect(page.getByLabel("提問")).toHaveValue("");
});

test("等待回答時顯示處理中", async ({ page }) => {
  await setup(page, async () => {
    await new Promise((r) => setTimeout(r, 500));
    return { content: "好", original_only: false, citations: [CITATION] };
  });
  await ask(page, "怎麼申請");
  await expect(page.getByTestId("answer-pending")).toBeVisible();
  await expect(page.getByTestId("answer-pending")).toHaveCount(0);
});
