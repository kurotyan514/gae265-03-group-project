import { expect, type Page, test } from "@playwright/test";

// 條款上傳的示範模式：請求全部攔截成固定的事件序列，不真的上傳、不呼叫 LLM。
const JOB_ID = "11111111-1111-4111-8111-111111111111";
const REASON = "內容是旅遊不便險的保險契約條文";

type Ev = {
  seq: number;
  step: string;
  status: string;
  message: string;
  current: number | null;
  total: number | null;
  data: Record<string, unknown> | null;
};

const ev = (
  seq: number,
  step: string,
  status: string,
  message: string,
  extra: Partial<Ev> = {},
): Ev => ({ seq, step, status, message, current: null, total: null, data: null, ...extra });

const EVENTS: Ev[] = [
  ev(1, "extract", "running", "讀取 a.pdf"),
  ev(2, "extract", "ok", "共 3 頁", { current: 3, total: 3 }),
  ev(3, "classify", "running", "判斷是否為保險條款"),
  ev(4, "classify", "ok", `是保險條款：${REASON}`, { data: { insurance_name: "旅遊不便險" } }),
  ev(5, "chunk", "ok", "切出 5 條條文", { current: 5, total: 5 }),
  ev(6, "validate", "ok", "驗證通過，0 個提醒", { data: { issues: [] } }),
  ev(7, "embed", "running", "計算向量", { current: 0, total: 5 }),
  ev(8, "embed", "running", "計算向量 2/5", { current: 2, total: 5 }),
  ev(9, "embed", "running", "計算向量 5/5", { current: 5, total: 5 }),
  ev(10, "embed", "ok", "完成 5 筆向量（text-embedding-3-large）", { current: 5, total: 5 }),
  ev(11, "import", "ok", "寫入 FUBON07 旅遊不便險：5 條條文"),
  ev(12, "done", "ok", "完成", { data: { rules: 5 } }),
];

const JOB = {
  id: JOB_ID,
  filename: "a.pdf",
  insurance_code: "FUBON07",
  insurance_name: "旅遊不便險",
  status: "done",
  summary: null,
  created_at: "2026-11-02T00:00:00Z",
};

async function mockJob(page: Page) {
  await page.route("**/api/v1/ingest/jobs", (route) =>
    route.request().method() === "GET" ? route.fulfill({ json: [JOB] }) : route.continue(),
  );
  await page.route(`**/api/v1/ingest/jobs/${JOB_ID}`, (route) =>
    route.fulfill({ json: { ...JOB, events: EVENTS } }),
  );
}

async function openJob(page: Page, query: string) {
  await mockJob(page);
  await page.goto(`/dev/ingest${query}`);
  await page
    .getByTestId("jobs")
    .getByRole("button", { name: /a\.pdf/ })
    .click();
}

test("示範模式切換鈕同步網址參數", async ({ page }) => {
  await mockJob(page);
  await page.goto("/dev/ingest");
  const toggle = page.getByTestId("demo-toggle");
  await expect(toggle).toHaveAttribute("aria-checked", "false");
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-checked", "true");
  await expect(page).toHaveURL(/demo=1/);
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-checked", "false");
  await expect(page).not.toHaveURL(/demo=1/);
});

test("直接開帶 demo=1 的網址，示範模式就是開啟的", async ({ page }) => {
  await mockJob(page);
  await page.goto("/dev/ingest?demo=1");
  await expect(page.getByTestId("demo-toggle")).toHaveAttribute("aria-checked", "true");
});

test("沒有示範參數時行為不變：沒有工具名稱，步驟一次到位", async ({ page }) => {
  await openJob(page, "");
  await expect(page.getByTestId("step-import")).toHaveAttribute("data-status", "ok");
  await expect(page.getByTestId("step-classify")).toHaveAttribute("data-status", "ok");
  await expect(page.getByTestId("tool-extract")).toHaveCount(0);
  await expect(page.getByTestId("llm-bubble")).toHaveCount(0);
});

test("示範模式：每個步驟顯示真實函式名與程式工具／LLM 判斷標籤", async ({ page }) => {
  await openJob(page, "?demo=1&speed=50");
  await expect(page.getByTestId("step-import")).toHaveAttribute("data-status", "ok");

  const expected: Record<string, [string, string]> = {
    extract: ["extract_pages", "程式工具"],
    classify: ["llm_classify", "LLM 判斷"],
    chunk: ["split_into_chunks", "程式工具"],
    repair: ["repair_articles", "程式工具"],
    validate: ["validate_articles", "程式工具"],
    embed: ["aembed_documents", "程式工具"],
    import: ["import_catalog", "程式工具"],
  };
  for (const [step, [fn, kind]] of Object.entries(expected)) {
    if (step === "repair") continue; // 這份事件序列沒有修復，不會顯示
    await expect(page.getByTestId(`tool-${step}`)).toContainText(`${fn}()`);
    await expect(page.getByTestId(`kind-${step}`)).toHaveText(kind);
  }
});

test("示範模式：判斷是否為條款那步用對話氣泡顯示 LLM 的理由", async ({ page }) => {
  await openJob(page, "?demo=1&speed=50");
  await expect(page.getByTestId("llm-bubble")).toContainText(REASON);
  // 其他步驟沒有 LLM 氣泡
  await expect(page.getByTestId("llm-bubble")).toHaveCount(1);
});

test("示範模式：事件逐步出現，不會一次全部到位", async ({ page }) => {
  await openJob(page, "?demo=1"); // 預設倍速：每步至少停留 1.5 秒以上
  await expect(page.getByTestId("step-extract")).toHaveAttribute("data-status", "running");
  // 後面的步驟還沒演到
  await expect(page.getByTestId("step-import")).toHaveAttribute("data-status", "pending");
  await expect(page.getByTestId("step-embed")).toHaveAttribute("data-status", "pending");
  await expect(page.getByTestId("tool-import")).toHaveCount(0);
});

test("示範模式：計算向量的連續進度最後停在最新值", async ({ page }) => {
  await openJob(page, "?demo=1&speed=50");
  await expect(page.getByTestId("step-embed")).toHaveAttribute("data-status", "ok");
  await expect(page.getByTestId("step-embed").locator("progress")).toHaveAttribute("value", "5");
});

const STATION_TOOLS = [
  ["extract", "extract_pages"],
  ["classify", "llm_classify"],
  ["chunk", "split_into_chunks"],
  ["repair", "repair_articles"],
  ["validate", "validate_articles"],
  ["embed", "aembed_documents"],
  ["import", "import_catalog"],
] as const;

test("進度軌道：示範模式下有 7 個站點，站名是工具名稱", async ({ page }) => {
  await openJob(page, "?demo=1&speed=50");
  await expect(page.getByTestId("track")).toBeVisible();
  await expect(
    page.locator('[data-testid^="station-"]:not([data-testid^="station-sub"])'),
  ).toHaveCount(7);
  for (const [step, tool] of STATION_TOOLS) {
    await expect(page.getByTestId(`station-${step}`)).toContainText(tool);
  }
});

test("進度軌道：示範模式關閉時不出現", async ({ page }) => {
  await openJob(page, "");
  await expect(page.getByTestId("step-import")).toHaveAttribute("data-status", "ok");
  await expect(page.getByTestId("track")).toHaveCount(0);
});

test("進度軌道：小人跟著步驟前進", async ({ page }) => {
  // 倍速 0.4：每步停留約 3.7 秒，慢機器也來得及看到中間那一站
  await openJob(page, "?demo=1&speed=0.4");
  const walker = page.getByTestId("walker");
  await expect(walker).toHaveAttribute("data-station", /start|extract/);
  await expect(page.getByTestId("station-classify")).toHaveAttribute("data-state", "pending");
  await expect(walker).toHaveAttribute("data-station", "classify", { timeout: 15_000 });
  await expect(page.getByTestId("station-extract")).toHaveAttribute("data-state", "done");
  await expect(page.getByTestId("station-classify")).toHaveAttribute("data-state", "current");
});

test("進度軌道：剛載入不會原地踏步，換站走完後站定", async ({ page }) => {
  await openJob(page, "?demo=1&speed=0.4");
  const walker = page.getByTestId("walker");
  await expect(walker).toHaveAttribute("data-walking", "false"); // 沒有位移就不走路
  await expect(walker).toHaveAttribute("data-station", "classify", { timeout: 15_000 });
  await expect(walker).toHaveAttribute("data-walking", "true"); // 換站時走路
  await expect(walker).toHaveAttribute("data-walking", "false"); // 走到了就站定
});

test("進度軌道：走完全部步驟後小人在終點，所有站點完成", async ({ page }) => {
  await openJob(page, "?demo=1&speed=50");
  await expect(page.getByTestId("walker")).toHaveAttribute("data-station", "import");
  for (const [step] of STATION_TOOLS) {
    await expect(page.getByTestId(`station-${step}`)).toHaveAttribute("data-state", "done");
  }
});

test("進度軌道：計算向量站顯示已完成筆數與總筆數", async ({ page }) => {
  await openJob(page, "?demo=1&speed=50");
  await expect(page.getByTestId("station-sub-embed")).toHaveText("5/5");
});
