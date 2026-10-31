import { delay, HttpResponse, http, sse } from "msw";
import { setupWorker } from "msw/browser";
import type {
  DevRuleList,
  DevRuleOut,
  HealthStatus,
  IngestEventOut,
  IngestJobDetail,
  IngestJobOut,
  InsuranceOut,
  QuoteResponse,
  SearchHitOut,
} from "../client/types.gen";

const RULES: DevRuleOut[] = [
  {
    insurance_code: "T113",
    insurance_name: "安心遊個人旅行綜合保險：行動電話被竊損失保險",
    article_no: 21,
    chapter: "條文二十一",
    title: "承保範圍",
    content:
      "被保險人於旅行期間，行動電話遭竊盜、強盜或搶奪所致之損失，本公司負賠償責任。（假資料）",
    section: null,
    source_file: "T113.pdf",
    page_start: 3,
    page_end: 3,
    embedding_models: ["text-embedding-3-large"],
    embedding_dimensions: 1024,
  },
  {
    insurance_code: "T068",
    insurance_name: "旅行平安保險",
    article_no: 1,
    chapter: "條文一",
    title: "契約構成",
    content: "本保險契約，包括保險單條款、要保書及其他約定書。（假資料）",
    section: "第一章 共同條款",
    source_file: "T068.pdf",
    page_start: 1,
    page_end: 2,
    embedding_models: [],
    embedding_dimensions: null,
  },
];

const INSURANCES: InsuranceOut[] = [
  { code: "T068", name: "旅行平安保險", rule_count: 1 },
  { code: "T113", name: "安心遊個人旅行綜合保險：行動電話被竊損失保險", rule_count: 1 },
];

const MOCK_JOB: IngestJobOut = {
  id: "00000000-0000-0000-0000-000000000001",
  filename: "T113.pdf",
  insurance_code: "T113",
  insurance_name: "旅遊不便險",
  status: "running",
  summary: null,
  created_at: "2026-10-30T06:00:00Z",
};

const ev = (
  seq: number,
  step: string,
  status: string,
  message: string,
  current: number | null = null,
  total: number | null = null,
  data: IngestEventOut["data"] = null,
): IngestEventOut => ({ seq, step, status, message, current, total, data });

// 第一個事件由 GET job 回，其餘走 SSE，模擬 agent 逐步執行
const MOCK_EVENTS: IngestEventOut[] = [
  ev(1, "extract", "ok", "共 6 頁", 6, 6),
  ev(2, "classify", "ok", "是保險條款：有條文結構（假資料）"),
  ev(3, "chunk", "ok", "切出 12 條條文", 12, 12),
  ev(4, "validate", "warning", "驗證通過，1 個提醒", null, null, {
    issues: [{ level: "warning", message: "條文十二沒有標題" }],
  }),
  ev(5, "embed", "running", "計算向量 6/12", 6, 12),
  ev(6, "embed", "ok", "完成 12 筆向量", 12, 12),
  ev(7, "import", "ok", "寫入 T113 旅遊不便險：12 條條文"),
  ev(8, "done", "ok", "完成", null, null, { rules: 12, embeddings: 12 }),
];

// 假資料模式（`VITE_MOCK=true`）攔下的 API；回應型別用產生的 client，後端 schema 改了這裡會型別錯誤
const handlers = [
  http.get("*/api/v1/health", () =>
    HttpResponse.json<HealthStatus>({ status: "ok", db: "ok (mock)", pgvector: "ok (mock)" }),
  ),
  // API 測試台在執行時讀這份 OpenAPI；假資料模式給最小的一份
  http.get("*/api/v1/openapi.json", () =>
    HttpResponse.json({
      paths: {
        "/api/v1/quote": {
          post: {
            operationId: "quote_plans",
            summary: "報價（假資料）",
            requestBody: {
              content: {
                "application/json": {
                  examples: {
                    solo: {
                      summary: "單人 5 天",
                      value: { days: 5, travelers: [{ age: 30 }], illness_medical: 300000 },
                    },
                  },
                },
              },
            },
          },
        },
        "/api/v1/rules": {
          get: {
            operationId: "list_all_rules",
            summary: "全部條文（假資料）",
            parameters: [{ name: "limit", in: "query", schema: { default: 100 } }],
          },
        },
      },
    }),
  ),
  http.get("*/api/v1/insurances", () => HttpResponse.json<InsuranceOut[]>(INSURANCES)),
  http.get("*/api/v1/rules", ({ request }) => {
    const params = new URL(request.url).searchParams;
    const code = params.get("insurance_code");
    const q = params.get("q");
    const items = RULES.filter(
      (r) =>
        (!code || r.insurance_code === code) &&
        (!q || r.title.includes(q) || r.content.includes(q)),
    );
    return HttpResponse.json<DevRuleList>({ total: items.length, items });
  }),
  http.post("*/api/v1/rules/search", () =>
    HttpResponse.json<SearchHitOut[]>(
      RULES.slice(0, 1).map((r) => ({
        ...r,
        citation: `${r.insurance_name} ${r.chapter} ${r.title}（${r.source_file} 第 ${r.page_start} 頁）`,
        score: 0.0328,
        sources: ["vector", "keyword"],
        similarity: 0.52,
      })),
    ),
  ),
  http.get("*/api/v1/ingest/jobs", () => HttpResponse.json<IngestJobOut[]>([MOCK_JOB])),
  http.post("*/api/v1/ingest/jobs", () =>
    HttpResponse.json<IngestJobOut>(MOCK_JOB, { status: 202 }),
  ),
  http.get("*/api/v1/ingest/jobs/:id", () =>
    HttpResponse.json<IngestJobDetail>({ ...MOCK_JOB, events: MOCK_EVENTS.slice(0, 1) }),
  ),
  sse<{ ingest: string; end: string }>("*/api/v1/ingest/jobs/:id/events", async ({ client }) => {
    for (const event of MOCK_EVENTS.slice(1)) {
      await delay(400);
      client.send({ event: "ingest", id: String(event.seq), data: JSON.stringify(event) });
    }
    client.send({ event: "end", data: JSON.stringify({ status: "done" }) });
  }),
  http.post("*/api/v1/quote", () =>
    HttpResponse.json<QuoteResponse>({ plans: [], unavailable: [] }),
  ),
];

/** 只由 main.tsx 在 `VITE_MOCK` 判斷裡 dynamic import，正式 build 不會包含。 */
export async function startMockWorker(): Promise<void> {
  // 沒寫 handler 的請求照常送出（例如 Vite 自己的模組）
  await setupWorker(...handlers).start({ onUnhandledFrame: "bypass" });
}
