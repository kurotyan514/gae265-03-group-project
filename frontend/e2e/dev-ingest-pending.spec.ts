import { expect, test } from "@playwright/test";

// 待確認條文：請求全部攔截成固定資料，不真的上傳、不算向量。
const JOB_ID = "22222222-2222-4222-8222-222222222222";

const article = (no: number, status = "pending", extra: Record<string, unknown> = {}) => ({
  article_no: no,
  title: `第 ${no} 條標題`,
  chapter: "第一章",
  section: null,
  content: `第 ${no} 條內容`,
  page_start: 2,
  page_end: 3,
  status,
  edited: false,
  findings: [
    {
      rule: "A2-content",
      status: "FAIL",
      severity: "高",
      message: "內容與 PDF 不符",
      suggestion: "對照 PDF 第 2 頁",
      evidence: { pdf: "PDF 的文字", chunk: "入庫的文字" },
    },
  ],
  ...extra,
});

const JOB = {
  id: JOB_ID,
  filename: "a.pdf",
  insurance_code: "FUBON07",
  insurance_name: "旅遊不便險",
  summary: null,
  created_at: "2026-11-02T00:00:00Z",
};

const detail = (status: string, articles: ReturnType<typeof article>[]) => ({
  ...JOB,
  status,
  events: [
    { seq: 1, step: "done", status: "ok", message: "完成", current: null, total: null, data: null },
  ],
  articles,
});

test("待確認條文：看原因、放行一條、改字後放行一條", async ({ page }) => {
  let current = detail("needs_review", [article(1), article(2)]);
  const calls: string[] = [];

  await page.route("**/api/v1/ingest/jobs", (route) =>
    route.request().method() === "GET"
      ? route.fulfill({ json: [{ ...JOB, status: current.status }] })
      : route.continue(),
  );
  await page.route(`**/api/v1/ingest/jobs/${JOB_ID}`, (route) => route.fulfill({ json: current }));
  await page.route(`**/api/v1/ingest/jobs/${JOB_ID}/articles/1/release`, (route) => {
    calls.push("release 1");
    current = detail("needs_review", [article(1, "released"), article(2)]);
    return route.fulfill({ json: current });
  });
  await page.route(`**/api/v1/ingest/jobs/${JOB_ID}/articles/2/edit`, (route) => {
    calls.push(`edit 2 ${route.request().postData()}`);
    current = detail("done", [article(1, "released"), article(2, "released", { edited: true })]);
    return route.fulfill({ json: current });
  });

  await page.goto("/dev/ingest");
  await page
    .getByTestId("jobs")
    .getByRole("button", { name: /a\.pdf/ })
    .click();

  // 看得到原因與 PDF 對照
  const first = page.getByTestId("pending-1");
  await expect(first).toContainText("內容與 PDF 不符");
  await expect(first).toContainText("PDF 的文字");
  await expect(first).toContainText("入庫的文字");
  await expect(page.getByTestId("pending-articles")).toContainText("2 條待處理");

  // 放行第 1 條
  await first.getByTestId("release").click();
  await expect(page.getByTestId("pending-1")).toHaveCount(0);
  await expect(page.getByTestId("processed-articles")).toContainText("第 1 條");
  await expect(page.getByTestId("pending-articles")).toContainText("1 條待處理");

  // 改字後放行第 2 條：原因必填
  const second = page.getByTestId("pending-2");
  await second.getByTestId("edit").click();
  await second.getByTestId("edit-content").fill("改過的內容");
  await expect(second.getByTestId("edit-submit")).toBeDisabled();
  await second.getByTestId("edit-reason").fill("實際保單的寫法");
  await second.getByTestId("edit-submit").click();

  await expect(page.getByTestId("pending-2")).toHaveCount(0);
  await expect(page.getByTestId("job-status")).toHaveText("完成");
  await expect(page.getByTestId("processed-articles")).toContainText("已改字");
  expect(calls[0]).toBe("release 1");
  expect(calls[1]).toContain("改過的內容");
  expect(calls[1]).toContain("實際保單的寫法");
});

test("待確認條文：處理失敗時顯示錯誤，這一條仍待處理", async ({ page }) => {
  const current = detail("needs_review", [article(1)]);
  await page.route("**/api/v1/ingest/jobs", (route) =>
    route.fulfill({ json: [{ ...JOB, status: current.status }] }),
  );
  await page.route(`**/api/v1/ingest/jobs/${JOB_ID}`, (route) => route.fulfill({ json: current }));
  await page.route(`**/api/v1/ingest/jobs/${JOB_ID}/articles/1/release`, (route) =>
    route.fulfill({ status: 409, json: { detail: "這一條已經被處理過了" } }),
  );

  await page.goto("/dev/ingest");
  await page
    .getByTestId("jobs")
    .getByRole("button", { name: /a\.pdf/ })
    .click();
  await page.getByTestId("pending-1").getByTestId("release").click();

  await expect(page.getByTestId("pending-error")).toHaveText("這一條已經被處理過了");
  await expect(page.getByTestId("pending-1")).toBeVisible();
});
