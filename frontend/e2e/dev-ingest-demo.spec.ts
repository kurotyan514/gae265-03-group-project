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
  ev(4, "classify", "ok", `是保險條款：${REASON}`, {
    data: { insurance_name: "旅遊不便險", reason: REASON },
  }),
  ev(5, "chunk", "ok", "切出 5 條條文", { current: 5, total: 5 }),
  ev(6, "validate", "ok", "驗證通過，0 個提醒", { data: { issues: [] } }),
  ev(7, "embed", "running", "計算向量", { current: 0, total: 5 }),
  ev(8, "embed", "running", "計算向量 2/5", { current: 2, total: 5 }),
  ev(9, "embed", "running", "計算向量 5/5", { current: 5, total: 5 }),
  ev(10, "embed", "ok", "完成 5 筆向量（text-embedding-3-large）", { current: 5, total: 5 }),
  ev(11, "import", "ok", "寫入 FUBON07 旅遊不便險：5 條條文"),
  ev(12, "selfcheck", "running", "檢索自檢"),
  ev(13, "selfcheck", "ok", "檢索自檢：5/5 條在前 3 名找得到自己（100%）"),
  ev(14, "done", "ok", "完成", { data: { rules: 5 } }),
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

type Scenario = { events: Ev[]; status: string };
const COMPLETED: Scenario = { events: EVENTS, status: "done" };

async function mockJob(page: Page, scenario: Scenario = COMPLETED) {
  const job = { ...JOB, status: scenario.status };
  await page.route("**/api/v1/ingest/jobs", (route) =>
    route.request().method() === "GET" ? route.fulfill({ json: [job] }) : route.continue(),
  );
  await page.route(`**/api/v1/ingest/jobs/${JOB_ID}`, (route) =>
    route.fulfill({ json: { ...job, events: scenario.events } }),
  );
}

async function openJob(page: Page, query: string, scenario: Scenario = COMPLETED) {
  await mockJob(page, scenario);
  await page.goto(`/dev/ingest${query}`);
  await page
    .getByTestId("jobs")
    .getByRole("button", { name: /a\.pdf/ })
    .click();
}

/** 已完成的工作在示範模式預設直接顯示結果，要先按「重播」才會慢速演出。 */
async function playJob(page: Page, query: string, scenario: Scenario = COMPLETED) {
  await openJob(page, query, scenario);
  await page.getByTestId("replay").click();
}

/** 即時處理中的工作：詳情只有前幾筆事件，其餘由 SSE 送來，最後送 end。 */
async function openLiveJob(page: Page, query: string, scenario: Scenario, alreadyStored: number) {
  const job = { ...JOB, status: "running" };
  await page.route("**/api/v1/ingest/jobs", (route) =>
    route.request().method() === "GET" ? route.fulfill({ json: [job] }) : route.continue(),
  );
  await page.route(`**/api/v1/ingest/jobs/${JOB_ID}`, (route) =>
    route.fulfill({ json: { ...job, events: scenario.events.slice(0, alreadyStored) } }),
  );
  const frames = scenario.events
    .slice(alreadyStored)
    .map((e) => `event: ingest\ndata: ${JSON.stringify(e)}\n\n`);
  frames.push(`event: end\ndata: ${JSON.stringify({ status: scenario.status })}\n\n`);
  const sse = frames.join("");
  await page.route(`**/api/v1/ingest/jobs/${JOB_ID}/events*`, (route) =>
    route.fulfill({ status: 200, headers: { "content-type": "text/event-stream" }, body: sse }),
  );
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
  await playJob(page, "?demo=1&speed=50");
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
  await playJob(page, "?demo=1&speed=50");
  await expect(page.getByTestId("llm-bubble")).toContainText(REASON);
  // 其他步驟沒有 LLM 氣泡
  await expect(page.getByTestId("llm-bubble")).toHaveCount(1);
});

test("示範模式：事件逐步出現，不會一次全部到位", async ({ page }) => {
  await playJob(page, "?demo=1"); // 預設倍速：每步至少停留 1.5 秒以上
  await expect(page.getByTestId("step-extract")).toHaveAttribute("data-status", "running");
  // 後面的步驟還沒演到
  await expect(page.getByTestId("step-import")).toHaveAttribute("data-status", "pending");
  await expect(page.getByTestId("step-embed")).toHaveAttribute("data-status", "pending");
  await expect(page.getByTestId("tool-import")).toHaveCount(0);
});

test("示範模式：計算向量的連續進度最後停在最新值", async ({ page }) => {
  await playJob(page, "?demo=1&speed=50");
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
  ["selfcheck", "check_insurance"],
] as const;

test("進度軌道：示範模式下有 8 個站點，站名是工具名稱", async ({ page }) => {
  await playJob(page, "?demo=1&speed=50");
  await expect(page.getByTestId("track")).toBeVisible();
  await expect(
    page.locator('[data-testid^="station-"]:not([data-testid^="station-sub"])'),
  ).toHaveCount(8);
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
  await playJob(page, "?demo=1&speed=0.4");
  const walker = page.getByTestId("walker");
  await expect(walker).toHaveAttribute("data-station", /start|extract/);
  await expect(page.getByTestId("station-classify")).toHaveAttribute("data-state", "pending");
  await expect(walker).toHaveAttribute("data-station", "classify", { timeout: 15_000 });
  await expect(page.getByTestId("station-extract")).toHaveAttribute("data-state", "done");
  await expect(page.getByTestId("station-classify")).toHaveAttribute("data-state", "current");
});

test("進度軌道：剛載入不會原地踏步，換站走完後站定", async ({ page }) => {
  await playJob(page, "?demo=1&speed=0.4");
  const walker = page.getByTestId("walker");
  await expect(walker).toHaveAttribute("data-walking", "false"); // 沒有位移就不走路
  await expect(walker).toHaveAttribute("data-station", "classify", { timeout: 15_000 });
  await expect(walker).toHaveAttribute("data-walking", "true"); // 換站時走路
  await expect(walker).toHaveAttribute("data-walking", "false"); // 走到了就站定
});

test("進度軌道：走完全部步驟後小人在終點，所有站點完成", async ({ page }) => {
  await playJob(page, "?demo=1&speed=50");
  await expect(page.getByTestId("walker")).toHaveAttribute("data-station", "selfcheck");
  for (const [step] of STATION_TOOLS) {
    await expect(page.getByTestId(`station-${step}`)).toHaveAttribute("data-state", "done");
  }
});

test("進度軌道：計算向量站顯示已完成筆數與總筆數", async ({ page }) => {
  await playJob(page, "?demo=1&speed=50");
  await expect(page.getByTestId("station-sub-embed")).toHaveText("5/5");
});

// 三種結局：被拒絕（不是條款）、處理失敗、驗證未通過等人工確認
const REJECTED: Scenario = {
  status: "rejected",
  events: [
    ev(1, "extract", "running", "讀取 a.pdf"),
    ev(2, "extract", "ok", "共 3 頁", { current: 3, total: 3 }),
    ev(3, "classify", "running", "判斷是否為保險條款"),
    ev(4, "classify", "error", "LLM 判斷不是條款：這是一份食譜，不是保險契約", {
      data: { by: "llm", reason: "這是一份食譜，不是保險契約" },
    }),
    ev(5, "done", "error", "不是保險條款"),
  ],
};

const FAILED_AT_EXTRACT: Scenario = {
  status: "failed",
  events: [
    ev(1, "extract", "running", "讀取 a.pdf"),
    ev(2, "extract", "error", "PDF 沒有可擷取的文字（可能是掃描檔，需要 OCR）"),
    ev(3, "done", "error", "無法處理，未寫入"),
  ],
};

const FAILED_WITHOUT_STEP: Scenario = {
  status: "failed",
  events: [
    ev(1, "extract", "ok", "共 3 頁", { current: 3, total: 3 }),
    ev(2, "classify", "ok", "是保險條款：旅遊不便險"),
    ev(3, "chunk", "ok", "切出 5 條條文", { current: 5, total: 5 }),
    ev(4, "done", "error", "處理失敗：資料庫連線中斷"),
  ],
};

const NEEDS_REVIEW: Scenario = {
  status: "needs_review",
  events: [
    ev(1, "extract", "running", "讀取 a.pdf"),
    ev(2, "extract", "ok", "共 3 頁", { current: 3, total: 3 }),
    ev(3, "classify", "running", "判斷是否為保險條款"),
    ev(4, "classify", "ok", "是保險條款：旅遊不便險", {
      data: { insurance_name: "旅遊不便險", reason: "旅遊不便險" },
    }),
    ev(5, "chunk", "ok", "切出 5 條條文", { current: 5, total: 5 }),
    ev(6, "validate", "error", "驗證未通過：1 個錯誤", {
      data: { issues: [{ level: "error", message: "第 3 條缺漏" }] },
    }),
    ev(7, "done", "warning", "驗證未通過，等待人工確認", { data: { pending: 5 } }),
  ],
};

test("結局：被拒絕時小人停在判斷那站並顯示 LLM 的原因", async ({ page }) => {
  await playJob(page, "?demo=1&speed=50", REJECTED);
  await expect(page.getByTestId("walker")).toHaveAttribute("data-outcome", "failed");
  await expect(page.getByTestId("walker")).toHaveAttribute("data-station", "classify");
  await expect(page.getByTestId("station-extract")).toHaveAttribute("data-state", "done");
  await expect(page.getByTestId("station-classify")).toHaveAttribute("data-state", "failed");
  await expect(page.getByTestId("station-chunk")).toHaveAttribute("data-state", "pending");
  await expect(page.getByTestId("track-outcome")).toContainText("這是一份食譜");
  await expect(page.getByTestId("job-status")).toHaveText("不是條款");
});

test("結局：處理失敗時小人停在出錯的那站並顯示原因", async ({ page }) => {
  await playJob(page, "?demo=1&speed=50", FAILED_AT_EXTRACT);
  await expect(page.getByTestId("walker")).toHaveAttribute("data-outcome", "failed");
  await expect(page.getByTestId("walker")).toHaveAttribute("data-station", "extract");
  await expect(page.getByTestId("station-extract")).toHaveAttribute("data-state", "failed");
  await expect(page.getByTestId("track-outcome")).toContainText("需要 OCR");
  await expect(page.getByTestId("job-status")).toHaveText("失敗");
});

test("結局：終局錯誤沒有指定步驟時，停在最後走到的那站", async ({ page }) => {
  await playJob(page, "?demo=1&speed=50", FAILED_WITHOUT_STEP);
  await expect(page.getByTestId("walker")).toHaveAttribute("data-station", "chunk");
  await expect(page.getByTestId("station-chunk")).toHaveAttribute("data-state", "failed");
  await expect(page.getByTestId("track-outcome")).toContainText("資料庫連線中斷");
});

test("結局：待人工確認時，確認按鈕要等動畫演完才出現（即時處理中的工作）", async ({ page }) => {
  await openLiveJob(page, "?demo=1", NEEDS_REVIEW, 2); // 預設倍速，整段動畫要好幾秒
  await expect(page.getByTestId("job-status")).toHaveText("處理中");
  await expect(page.getByTestId("approve")).toHaveCount(0);

  await expect(page.getByTestId("approve")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("job-status")).toHaveText("待人工確認");
  await expect(page.getByTestId("walker")).toHaveAttribute("data-outcome", "review");
  await expect(page.getByTestId("station-validate")).toHaveAttribute("data-state", "review");
});

test("結局：沒有示範參數時，結局與確認按鈕一次到位（行為不變）", async ({ page }) => {
  await openJob(page, "", NEEDS_REVIEW);
  await expect(page.getByTestId("job-status")).toHaveText("待人工確認");
  await expect(page.getByTestId("approve")).toBeVisible();
  await expect(page.getByTestId("track")).toHaveCount(0);
});

test("結局：示範模式下，左邊的紀錄清單也不會提前洩漏結果", async ({ page }) => {
  await playJob(page, "?demo=1", REJECTED); // 預設倍速，整段動畫要好幾秒
  const entry = page.getByTestId("jobs").getByRole("button", { name: /a\.pdf/ });
  await expect(entry).toContainText("處理中");
  await expect(entry).toContainText("不是條款", { timeout: 20_000 });
});

test("結局：失敗訊息以終局前最後一個步驟為準，不被更早的舊錯誤干擾", async ({ page }) => {
  const stale: Scenario = {
    status: "failed",
    events: [
      ev(1, "extract", "ok", "共 3 頁", { current: 3, total: 3 }),
      ev(2, "embed", "error", "暫時失敗，重試中"),
      ev(3, "embed", "ok", "完成 5 筆向量"),
      ev(4, "done", "error", "處理失敗：資料庫連線中斷"),
    ],
  };
  await playJob(page, "?demo=1&speed=50", stale);
  await expect(page.getByTestId("track-outcome")).toContainText("資料庫連線中斷");
  await expect(page.getByTestId("track-outcome")).not.toContainText("暫時失敗");
});

// ── 重播：已處理完的工作直接顯示結果，要演再按「重播」 ──
test("重播：已完成的工作在示範模式直接顯示最終結果，不自動播動畫", async ({ page }) => {
  await openJob(page, "?demo=1"); // 預設倍速：若有播動畫，這些要好幾秒才會到
  await expect(page.getByTestId("step-import")).toHaveAttribute("data-status", "ok");
  await expect(page.getByTestId("walker")).toHaveAttribute("data-station", "selfcheck");
  await expect(page.getByTestId("job-status")).toHaveText("完成");
  await expect(page.getByTestId("replay")).toBeVisible();
});

test("重播：失敗與被拒絕的工作直接顯示結局，也有重播鈕", async ({ page }) => {
  await openJob(page, "?demo=1", REJECTED);
  await expect(page.getByTestId("walker")).toHaveAttribute("data-outcome", "failed");
  await expect(page.getByTestId("track-outcome")).toContainText("這是一份食譜");
  await expect(page.getByTestId("replay")).toBeVisible();
});

test("重播：待人工確認的工作直接顯示確認按鈕與重播鈕", async ({ page }) => {
  await openJob(page, "?demo=1", NEEDS_REVIEW);
  await expect(page.getByTestId("approve")).toBeVisible();
  await expect(page.getByTestId("replay")).toBeVisible();
});

test("重播：處理中的工作沒有重播鈕", async ({ page }) => {
  await openLiveJob(page, "?demo=1", NEEDS_REVIEW, 2);
  await expect(page.getByTestId("job-status")).toHaveText("處理中");
  await expect(page.getByTestId("replay")).toHaveCount(0);
});

test("重播：沒有示範參數時不出現重播鈕", async ({ page }) => {
  await openJob(page, "");
  await expect(page.getByTestId("step-import")).toHaveAttribute("data-status", "ok");
  await expect(page.getByTestId("replay")).toHaveCount(0);
});

test("重播：按下後從頭慢速重演，演完回到與直接顯示相同的最終狀態", async ({ page }) => {
  await openJob(page, "?demo=1");
  await page.getByTestId("replay").click();
  // 預設倍速：剛按下去時還沒演到後面
  await expect(page.getByTestId("step-import")).toHaveAttribute("data-status", "pending");
  await expect(page.getByTestId("job-status")).toHaveText("處理中");
  await expect(page.getByTestId("replay")).toHaveCount(0);
  await expect(page.getByTestId("walker")).toHaveAttribute("data-station", /start|extract/);

  await expect(page.getByTestId("replay")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("step-import")).toHaveAttribute("data-status", "ok");
  await expect(page.getByTestId("walker")).toHaveAttribute("data-station", "selfcheck");
  await expect(page.getByTestId("job-status")).toHaveText("完成");
});

test("重播：可以連續重播多次", async ({ page }) => {
  await openJob(page, "?demo=1&speed=50");
  for (let i = 0; i < 2; i++) {
    await page.getByTestId("replay").click();
    await expect(page.getByTestId("replay")).toBeVisible();
    await expect(page.getByTestId("step-import")).toHaveAttribute("data-status", "ok");
  }
});

test("重播：只讀已存的事件，不送出任何會觸發處理的請求，也不重新讀取工作", async ({ page }) => {
  const writes: string[] = [];
  let detailReads = 0;
  let streams = 0;
  page.on("request", (r) => {
    if (!r.url().includes("/api/v1/ingest")) return;
    if (r.method() !== "GET") writes.push(`${r.method()} ${r.url()}`);
    else if (r.url().includes(`/ingest/jobs/${JOB_ID}/events`)) streams++;
    else if (r.url().endsWith(`/ingest/jobs/${JOB_ID}`)) detailReads++;
  });

  await openJob(page, "?demo=1&speed=50");
  await expect(page.getByTestId("replay")).toBeVisible();
  const before = detailReads;
  await page.getByTestId("replay").click();
  await expect(page.getByTestId("replay")).toBeVisible();
  await expect(page.getByTestId("step-import")).toHaveAttribute("data-status", "ok");

  expect(writes).toEqual([]);
  expect(detailReads).toBe(before);
  expect(streams).toBe(0);
});

test("重播：重演時左邊清單也先顯示處理中，演完才揭曉", async ({ page }) => {
  await openJob(page, "?demo=1", REJECTED);
  const entry = page.getByTestId("jobs").getByRole("button", { name: /a\.pdf/ });
  await expect(entry).toContainText("不是條款");
  await page.getByTestId("replay").click();
  await expect(entry).toContainText("處理中");
  await expect(entry).toContainText("不是條款", { timeout: 20_000 });
});

test("重播：重播後關掉再打開示範模式，不會自己重演", async ({ page }) => {
  await openJob(page, "?demo=1", REJECTED); // 預設倍速：整段重演約 4 秒以上
  await page.getByTestId("replay").click();
  await expect(page.getByTestId("replay")).toBeVisible({ timeout: 20_000 });

  const toggle = page.getByTestId("demo-toggle");
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-checked", "false");
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-checked", "true");
  // 不用會重試的斷言：要確認「一打開就是結果」，而不是重演後才變成結果
  expect(await page.getByTestId("job-status").textContent()).toBe("不是條款");
  await expect(page.getByTestId("replay")).toBeVisible();
});

test("重播：即時處理完之後才打開示範模式，直接顯示結果而不是重演", async ({ page }) => {
  await openLiveJob(page, "", REJECTED, 2); // 示範模式關著看完整個處理
  await expect(page.getByTestId("job-status")).toHaveText("不是條款");

  const toggle = page.getByTestId("demo-toggle");
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-checked", "true");
  expect(await page.getByTestId("job-status").textContent()).toBe("不是條款");
  await expect(page.getByTestId("replay")).toBeVisible();
});

test("重播：剛上傳的工作即使第一次讀取時已經結束，也從頭慢速演出", async ({ page }) => {
  await mockJob(page, REJECTED);
  await page.route("**/api/v1/ingest/jobs", (route) =>
    route.request().method() === "POST"
      ? route.fulfill({ status: 202, json: { ...JOB, status: "rejected" } })
      : route.fallback(),
  );
  await page.goto("/dev/ingest?demo=1");
  await page.getByTestId("file").setInputFiles({
    name: "a.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("x"),
  });
  await page.getByPlaceholder("FUBON07").fill("FUBON07");
  await page.getByPlaceholder("旅遊不便險").fill("旅遊不便險");
  await page.getByRole("button", { name: "上傳並處理" }).click();

  // 演出才會先停在「讀取中」；直接顯示的話第一步早就是完成
  await expect(page.getByTestId("step-extract")).toHaveAttribute("data-status", "running");
  await expect(page.getByTestId("step-classify")).toHaveAttribute("data-status", "pending");
  await expect(page.getByTestId("job-status")).toHaveText("不是條款", { timeout: 20_000 });
});

// ── 減少動態：尊重系統設定，關掉動畫與人為等待，資訊仍然完整 ──
const reduceMotion = (page: Page) => page.emulateMedia({ reducedMotion: "reduce" });

test("減少動態：只在系統設為減少動態時，切換鈕旁才出現提示", async ({ page }) => {
  await mockJob(page);
  await page.goto("/dev/ingest");
  await expect(page.getByTestId("demo-toggle")).toBeVisible();
  await expect(page.getByTestId("reduced-motion-note")).toHaveCount(0);

  await reduceMotion(page);
  await expect(page.getByTestId("reduced-motion-note")).toContainText("減少動態");
  await expect(page.getByTestId("reduced-motion-note")).toContainText("重播"); // 說明為什麼沒有重播鈕
});

test("減少動態：不加入人為的停留等待，事件到了就直接顯示", async ({ page }) => {
  await reduceMotion(page);
  await openLiveJob(page, "?demo=1", NEEDS_REVIEW, 2); // 一般倍速要 5 秒以上才演完
  await expect(page.getByTestId("approve")).toBeVisible({ timeout: 2_000 });
  await expect(page.getByTestId("job-status")).toHaveText("待人工確認");
});

test("減少動態：工具名稱、標籤與小人所在站點仍然完整可見", async ({ page }) => {
  await reduceMotion(page);
  await openLiveJob(page, "?demo=1", COMPLETED, 2);
  await expect(page.getByTestId("walker")).toHaveAttribute("data-station", "selfcheck");
  await expect(page.getByTestId("tool-classify")).toContainText("llm_classify()");
  await expect(page.getByTestId("kind-classify")).toHaveText("LLM 判斷");
  await expect(page.getByTestId("tool-import")).toContainText("import_catalog()");
  await expect(page.getByTestId("llm-bubble")).toContainText(REASON);
  await expect(page.getByTestId("station-import")).toHaveAttribute("data-state", "done");
});

/** 記錄小人的 data-walking 是否曾經變成 true；頁面載入前就裝好，才不會漏掉換站的瞬間。 */
async function trackWalking(page: Page) {
  await page.addInitScript(() => {
    const w = window as unknown as { __walked: boolean };
    w.__walked = false;
    new MutationObserver((records) => {
      for (const r of records) {
        if ((r.target as HTMLElement).getAttribute("data-walking") === "true") w.__walked = true;
      }
    }).observe(document, { subtree: true, attributes: true, attributeFilter: ["data-walking"] });
  });
}
const everWalked = (page: Page) =>
  page.evaluate(
    () =>
      new Promise<boolean>((resolve) =>
        // 等兩個畫面，讓換站後的 effect 都跑完再讀
        requestAnimationFrame(() =>
          requestAnimationFrame(() =>
            resolve((window as unknown as { __walked: boolean }).__walked),
          ),
        ),
      ),
  );

test("減少動態：小人不走路也不滑動，直接站在目前的站點", async ({ page }) => {
  await trackWalking(page);
  await reduceMotion(page);
  await openLiveJob(page, "?demo=1", COMPLETED, 2); // 會從第一站直接換到最後一站
  const walker = page.getByTestId("walker");
  await expect(walker).toHaveAttribute("data-station", "selfcheck");
  expect(await everWalked(page)).toBe(false);
  expect(await walker.evaluate((el) => getComputedStyle(el).transitionDuration)).toBe("0s");
});

test("沒有減少動態偏好時，小人換站會走路（對照組，確認偵測方法有效）", async ({ page }) => {
  await trackWalking(page);
  await openLiveJob(page, "?demo=1&speed=50", COMPLETED, 2);
  await expect(page.getByTestId("walker")).toHaveAttribute("data-station", "selfcheck");
  await expect.poll(() => everWalked(page)).toBe(true);
});

test("減少動態：重演沒有意義，不顯示重播鈕，已處理完的工作直接顯示結果", async ({ page }) => {
  await reduceMotion(page);
  await openJob(page, "?demo=1");
  await expect(page.getByTestId("step-import")).toHaveAttribute("data-status", "ok");
  await expect(page.getByTestId("replay")).toHaveCount(0);
});

const RUNNING_ONE_STEP: Scenario = {
  status: "running",
  events: [ev(1, "extract", "running", "讀取 a.pdf")],
};
const dotsAnimation = (page: Page) =>
  page
    .locator(".ingest-dots span")
    .first()
    .evaluate((el) => getComputedStyle(el).animationName);

test("減少動態：進行中的「…」不跳動", async ({ page }) => {
  await reduceMotion(page);
  await openLiveJob(page, "?demo=1", RUNNING_ONE_STEP, 1);
  await expect(page.getByTestId("step-extract")).toHaveAttribute("data-status", "running");
  expect(await dotsAnimation(page)).toBe("none");
});

test("沒有減少動態偏好時，進行中的「…」會跳動（對照組）", async ({ page }) => {
  await openLiveJob(page, "?demo=1", RUNNING_ONE_STEP, 1);
  await expect(page.getByTestId("step-extract")).toHaveAttribute("data-status", "running");
  expect(await dotsAnimation(page)).not.toBe("none");
});
