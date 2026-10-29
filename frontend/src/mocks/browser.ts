import { HttpResponse, http } from "msw";
import { setupWorker } from "msw/browser";
import type {
  DevRuleList,
  DevRuleOut,
  HealthStatus,
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

// 假資料模式（`VITE_MOCK=true`）攔下的 API；回應型別用產生的 client，後端 schema 改了這裡會型別錯誤
const handlers = [
  http.get("*/api/v1/health", () =>
    HttpResponse.json<HealthStatus>({ status: "ok", db: "ok (mock)", pgvector: "ok (mock)" }),
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
  http.post("*/api/v1/quote", () =>
    HttpResponse.json<QuoteResponse>({ plans: [], unavailable: [] }),
  ),
];

/** 只由 main.tsx 在 `VITE_MOCK` 判斷裡 dynamic import，正式 build 不會包含。 */
export async function startMockWorker(): Promise<void> {
  // 沒寫 handler 的請求照常送出（例如 Vite 自己的模組）
  await setupWorker(...handlers).start({ onUnhandledFrame: "bypass" });
}
