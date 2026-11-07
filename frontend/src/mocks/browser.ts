import { delay, HttpResponse, http, sse } from "msw";
import { setupWorker } from "msw/browser";
import type {
  AuthConfig,
  CitationOut,
  ComparisonIn,
  ComparisonOut,
  ComparisonPatch,
  Concern,
  ConversationOut,
  DevLoginIn,
  DevRuleList,
  DevRuleOut,
  HealthStatus,
  IngestEventOut,
  IngestJobDetail,
  IngestJobOut,
  InsuranceOut,
  MessageOut,
  PastComparisonOut,
  PlanCardOut,
  PlanOut,
  QuestionAnswerOut,
  QuoteResponse,
  ScenarioOut,
  SearchHitOut,
  UserOut,
} from "../client/types.gen";
import { incidentHandlers } from "./incident";

// 假資料模式的登入狀態：存在這個分頁的 sessionStorage，關掉分頁就登出。
// 不能只放記憶體：登入成功後整頁跳轉，記憶體會清空。
const USER_KEY = "mock-user";
const loadUser = (): UserOut | null => JSON.parse(sessionStorage.getItem(USER_KEY) ?? "null");
function saveUser(user: UserOut | null) {
  if (user) sessionStorage.setItem(USER_KEY, JSON.stringify(user));
  else sessionStorage.removeItem(USER_KEY);
}

const RULES: DevRuleOut[] = [
  {
    insurance_code: "FUBON05",
    insurance_name: "安心遊個人旅行綜合保險：行動電話被竊損失保險",
    approval_no: "富保業字第1100001835號函備查",
    approval_date: "110.08.04",
    article_no: 21,
    chapter: "條文二十一",
    title: "承保範圍",
    content:
      "被保險人於旅行期間，行動電話遭竊盜、強盜或搶奪所致之損失，本公司負賠償責任。（假資料）",
    section: null,
    source_file: "fubon.pdf",
    page_start: 3,
    page_end: 3,
    embedding_models: ["text-embedding-3-large"],
    embedding_dimensions: 1024,
  },
  {
    insurance_code: "FUBON01",
    insurance_name: "旅行平安保險",
    approval_no: "富保業字第1130004861號函備查",
    approval_date: "113.11.29",
    article_no: 1,
    chapter: "條文一",
    title: "契約構成",
    content: "本保險契約，包括保險單條款、要保書及其他約定書。（假資料）",
    section: "第一章 共同條款",
    source_file: "fubon.pdf",
    page_start: 1,
    page_end: 2,
    embedding_models: [],
    embedding_dimensions: null,
  },
];

const MOCK_PLAN: PlanOut = {
  id: "taian",
  name: "泰安國外旅平險（假資料）",
  insurances: [
    {
      code: "TAIAN01",
      name: "泰安產物旅行平安保險（標準型）",
      approval_no: "(113)精企字第123號函備查",
      approval_date: "113.06.27",
    },
    {
      code: "TAIAN03",
      name: "泰安產物海外突發疾病醫療健康保險(乙型)",
      approval_no: "(114)精算字第0000000130號函備查",
      approval_date: "114.07.30",
    },
  ],
};
const PLANS: PlanOut[] = [MOCK_PLAN];

// 假對話：問題含「未載明」回「保單未載明」、含「原文」回只顯示原文，其餘回有出處的白話說明。
// 不是在這裡建立的對話 id（含別人的）一律 404。
// 依對話 id 分開存；沒建立過的 id 回 404
const mockConversations = new Map<string, MessageOut[]>();
const MOCK_CITATION: CitationOut = {
  rule_id: "00000000-0000-0000-0000-0000000000e1",
  insurance_code: "TAIAN01",
  insurance_name: "泰安產物旅行平安保險（標準型）",
  article_no: 12,
  title: "保險事故的通知與保險金的申請時間",
  section: null,
  page_start: 5,
  page_end: 5,
  excerpt: "被保險人遭受意外傷害事故時，應於知悉後通知本公司，並檢具相關文件申請。（假資料）",
  score: 0.52,
};
const NOT_COVERED = "保單未載明，請向保險公司確認";
const ORIGINAL_NOTICE = "（無法產生白話說明，以下直接列出條款原文。）";

function mockReply(question: string, seq: number): MessageOut {
  const base = {
    id: `00000000-0000-0000-0000-00000000a${String(seq).padStart(3, "0")}`,
    seq,
    role: "assistant",
    created_at: new Date().toISOString(),
  };
  if (question.includes("未載明"))
    return { ...base, content: NOT_COVERED, original_only: false, citations: [] };
  if (question.includes("原文"))
    return {
      ...base,
      content: `${ORIGINAL_NOTICE}\n\n【${MOCK_CITATION.insurance_name} 第 12 條】\n${MOCK_CITATION.excerpt}`,
      original_only: true,
      citations: [MOCK_CITATION],
    };
  return {
    ...base,
    content: "發生意外後要盡快通知保險公司並備齊文件申請。（假回答）",
    original_only: false,
    citations: [MOCK_CITATION],
  };
}

const INSURANCES: InsuranceOut[] = [
  {
    code: "FUBON01",
    name: "富邦產物旅行平安保險",
    approval_no: "富保業字第1130004861號函備查",
    approval_date: "113.11.29",
    rule_count: 1,
  },
  {
    code: "FUBON05",
    name: "富邦產物安心遊個人旅行綜合保險",
    approval_no: "富保業字第1100001835號函備查",
    approval_date: "110.08.04",
    rule_count: 1,
  },
];

const MOCK_JOB: IngestJobOut = {
  id: "00000000-0000-0000-0000-000000000001",
  filename: "fubon.pdf",
  insurance_code: "FUBON07",
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
  ev(2, "classify", "ok", "是保險條款：有條文結構（假資料）", null, null, {
    reason: "有條文結構（假資料）",
  }),
  ev(3, "chunk", "ok", "切出 12 條條文", 12, 12),
  ev(4, "validate", "warning", "驗證通過，1 個提醒", null, null, {
    issues: [{ level: "warning", message: "條文十二沒有標題" }],
  }),
  ev(5, "embed", "running", "計算向量 6/12", 6, 12),
  ev(6, "embed", "ok", "完成 12 筆向量", 12, 12),
  ev(7, "import", "ok", "寫入 FUBON07 旅遊不便險：12 條條文"),
  ev(8, "done", "ok", "完成", null, null, { rules: 12, embeddings: 12 }),
];

// 比較紀錄依 id 存在記憶體，重新整理就不見；不檢查日期、年齡規則（前端表單已擋）
const mockComparisons = new Map<string, ComparisonOut>();
const NO_COMPARISON = { detail: "找不到這筆比較紀錄" };

// 假推薦：固定兩個方案，保費 = 保額（萬）× 2 元；不跑推薦規則，只讓 1-3 畫得出來
const MIN_SUM = 3_000_000;
const SUM_OPTIONS = [MIN_SUM, 5_000_000, 10_000_000];
function mockCard(plan_code: string, name: string, sum: number, concerns: Concern[]): PlanCardOut {
  return {
    plan_code,
    name,
    company: "假資料產物",
    url: "https://www.einsure.com.tw/product/travel",
    sum_insured: sum,
    recommended_sum_insured: MIN_SUM,
    sum_insured_options: SUM_OPTIONS,
    premium: (sum / 10_000) * 2,
    concern_amounts: concerns.map((concern) => ({ concern, amount: 1000 })),
  };
}
function mockRecommendation(
  concerns: Concern[],
  recSum = MIN_SUM,
  altSum = MIN_SUM,
): ComparisonOut["recommendation"] {
  if (concerns.length === 0) return null;
  const death = (sum: number) => [{ name: "身故失能保險金", amount: sum }];
  return {
    recommended: mockCard("mock_a", "假推薦方案", recSum, concerns),
    alternative: mockCard("mock_b", "假次推薦方案", altSum, concerns),
    reason: `你最在意「${concerns[0]}」，推薦方案在這一項是 2,000 元，次推薦是 1,000 元；保費多 100 元。（假資料）`,
    basis: [
      ...concerns.map((c) => `${c}：兩者相同（1,000 元 vs 1,000 元）`),
      "保費：兩者相同（600 元 vs 600 元）",
    ],
    table: [
      ...concerns.map((c) => ({
        key: c,
        label: c,
        explanation: `${c}的白話解釋。（假資料）`,
        concern: c,
        recommended: [{ name: `${c}保險`, amount: 2000 }],
        alternative: [],
      })),
      {
        key: "death",
        label: "身故",
        explanation: "身故的白話解釋。（假資料）",
        concern: null,
        recommended: death(recSum),
        alternative: death(altSum),
      },
      {
        key: "liability",
        label: "責任保險",
        explanation: "責任保險的白話解釋。（假資料）",
        concern: null,
        recommended: [],
        alternative: [],
      },
    ],
  };
}

// 假情境試算：固定 5 個情境，涵蓋使用者在意事項的標 ★ 排前面；兩個方案都用同一張假卡片，只讓 1-4 畫得出來
const MOCK_SCENARIOS: { tab: string; concerns: Concern[]; rows: string[]; note?: string }[] = [
  { tab: "航班延誤", concerns: ["班機延誤", "行李延誤"], rows: ["班機延誤", "行李延誤"] },
  { tab: "生病住院", concerns: ["突然生病就醫"], rows: ["海外突發疾病醫療"] },
  { tab: "行前取消", concerns: ["行程取消或更改"], rows: ["旅程取消"] },
  {
    tab: "錢包被偷",
    concerns: ["行李遺失或損壞", "證件遺失", "信用卡盜刷"],
    rows: ["行李損失", "旅行文件損失", "信用卡盜用"],
    note: "背包視為「類似容器」，包內物品可依損失申請，背包本身不賠。",
  },
  {
    tab: "騎車撞傷",
    concerns: ["需要緊急送醫或家屬趕來", "不小心弄傷別人或弄壞東西"],
    rows: ["意外傷害醫療", "緊急救援", "責任保險"],
  },
];
function mockScenarios(comparison: ComparisonOut): ScenarioOut[] {
  const rec = comparison.recommendation;
  if (!rec) return [];
  const rank = (concerns: Concern[]) =>
    Math.min(
      comparison.concerns.length,
      ...concerns.map((c) => comparison.concerns.indexOf(c)).filter((i) => i >= 0),
    );
  return [...MOCK_SCENARIOS]
    .sort((a, b) => rank(a.concerns) - rank(b.concerns))
    .map((s) => ({
      tab: s.tab,
      concerns: s.concerns,
      starred: rank(s.concerns) < comparison.concerns.length,
      story: `${s.tab}的情境故事。（假資料）`,
      assumption: "依實際收據，不假設金額",
      note: s.note ?? null,
      conclusion: `${rec.recommended.name}：${s.rows.map((r) => `${r} 依實際收據，最高 2,000 元`).join("、")}；${rec.alternative.name}：${s.rows.map((r) => `${r} 不在保障範圍`).join("、")}。`,
      rows: s.rows.map((name) => ({
        name,
        name_explanation: `${name}的白話解釋。（假資料）`,
        method: "實支實付",
        method_explanation: "依實際支出的費用給付。（假資料）",
        plans: [
          {
            plan_code: rec.recommended.plan_code,
            name: rec.recommended.name,
            company: rec.recommended.company,
            recommended: true,
            result: "在保障範圍內",
            benefit: `${name}保險`,
            max_amount: 2000,
            payout: null,
            outcome: "依實際收據，最高 2,000 元",
            basis: "假資料旅行平安保險 第 1 條",
          },
          {
            plan_code: rec.alternative.plan_code,
            name: rec.alternative.name,
            company: rec.alternative.company,
            recommended: false,
            result: "不在保障範圍",
            benefit: null,
            max_amount: null,
            payout: null,
            outcome: null,
            basis: null,
          },
        ],
      })),
    }));
}

// 假資料模式（`VITE_MOCK=true`）攔下的 API；回應型別用產生的 client，後端 schema 改了這裡會型別錯誤
const handlers = [
  ...incidentHandlers,
  http.get("*/api/v1/health", () =>
    HttpResponse.json<HealthStatus>({ status: "ok", db: "ok (mock)", pgvector: "ok (mock)" }),
  ),
  http.get("*/api/v1/auth/config", () =>
    HttpResponse.json<AuthConfig>({ dev_login: true, google_login: false }),
  ),
  http.get("*/api/v1/auth/me", () => {
    const user = loadUser();
    return user
      ? HttpResponse.json<UserOut>(user)
      : HttpResponse.json({ detail: "未登入" }, { status: 401 });
  }),
  http.post("*/api/v1/auth/dev-login", async ({ request }) => {
    const body = (await request.json()) as DevLoginIn;
    const user: UserOut = {
      id: "00000000-0000-0000-0000-0000000000aa",
      email: body.email.toLowerCase(),
      name: body.name ?? null,
      login_provider: "dev",
    };
    saveUser(user);
    return HttpResponse.json<UserOut>(user);
  }),
  http.get("*/api/v1/plans", () => HttpResponse.json<PlanOut[]>(PLANS)),
  http.post("*/api/v1/plans/:planId/conversations", () => {
    const id = `00000000-0000-0000-0000-0000000000c${mockConversations.size + 1}`;
    mockConversations.set(id, []);
    return HttpResponse.json<ConversationOut>(
      {
        id,
        title: MOCK_PLAN.name,
        plan_id: MOCK_PLAN.id,
        insurance_codes: MOCK_PLAN.insurances.map((i) => i.code),
      },
      { status: 201 },
    );
  }),
  http.get("*/api/v1/conversations/:id/messages", ({ params }) => {
    const messages = mockConversations.get(String(params.id));
    return messages
      ? HttpResponse.json<MessageOut[]>(messages)
      : HttpResponse.json({ detail: "找不到對話" }, { status: 404 });
  }),
  http.post("*/api/v1/conversations/:id/messages", async ({ params, request }) => {
    const mockMessages = mockConversations.get(String(params.id));
    if (!mockMessages) return HttpResponse.json({ detail: "找不到對話" }, { status: 404 });
    const { content } = (await request.json()) as { content: string };
    await delay(300);
    const seq = mockMessages.length + 1;
    mockMessages.push({
      id: `00000000-0000-0000-0000-00000000b${String(seq).padStart(3, "0")}`,
      seq,
      role: "user",
      content,
      original_only: false,
      created_at: new Date().toISOString(),
      citations: [],
    });
    const reply = mockReply(content, seq + 1);
    mockMessages.push(reply);
    return HttpResponse.json<MessageOut>(reply);
  }),
  http.post("*/api/v1/comparisons", async ({ request }) => {
    const body = (await request.json()) as ComparisonIn;
    const now = new Date().toISOString();
    const comparison: ComparisonOut = {
      concerns: [],
      note: "",
      ...body,
      id: crypto.randomUUID(),
      created_at: now,
      updated_at: now,
      recommendation: mockRecommendation(body.concerns ?? []),
    };
    mockComparisons.set(comparison.id, comparison);
    return HttpResponse.json<ComparisonOut>(comparison, { status: 201 });
  }),
  http.get("*/api/v1/comparisons", ({ request }) => {
    const limit = Number(new URL(request.url).searchParams.get("limit") ?? 3);
    const past = [...mockComparisons.values()]
      .reverse()
      .filter((c) => c.recommendation)
      .slice(0, limit)
      .map((c): PastComparisonOut => {
        const rec = c.recommendation as NonNullable<ComparisonOut["recommendation"]>;
        const plan = (card: PlanCardOut) => ({
          plan_id: card.plan_code,
          name: card.name,
          company: card.company,
          sum_insured: card.sum_insured,
        });
        const days = (Date.parse(c.return_date) - Date.parse(c.depart_date)) / 86_400_000 + 1;
        return {
          id: c.id,
          destination: c.destination,
          depart_date: c.depart_date,
          return_date: c.return_date,
          days,
          recommended: plan(rec.recommended),
          alternative: plan(rec.alternative),
        };
      });
    return HttpResponse.json<PastComparisonOut[]>(past);
  }),
  http.get("*/api/v1/comparisons/:id", ({ params }) => {
    const comparison = mockComparisons.get(String(params.id));
    return comparison
      ? HttpResponse.json<ComparisonOut>(comparison)
      : HttpResponse.json(NO_COMPARISON, { status: 404 });
  }),
  http.patch("*/api/v1/comparisons/:id", async ({ params, request }) => {
    const comparison = mockComparisons.get(String(params.id));
    if (!comparison) return HttpResponse.json(NO_COMPARISON, { status: 404 });
    // 前端只送有值的欄位，不會送 null
    const { recommended_sum_insured, alternative_sum_insured, ...body } =
      (await request.json()) as ComparisonPatch;
    const merged = { ...comparison, ...body } as ComparisonOut;
    const rec = comparison.recommendation;
    const recommendation =
      body.concerns === undefined && rec
        ? mockRecommendation(
            merged.concerns,
            recommended_sum_insured ?? rec.recommended.sum_insured,
            alternative_sum_insured ?? rec.alternative.sum_insured,
          )
        : mockRecommendation(merged.concerns);
    const updated = { ...merged, recommendation, updated_at: new Date().toISOString() };
    mockComparisons.set(updated.id, updated);
    return HttpResponse.json<ComparisonOut>(updated);
  }),
  http.get("*/api/v1/comparisons/:id/scenarios", ({ params }) => {
    const comparison = mockComparisons.get(String(params.id));
    return comparison
      ? HttpResponse.json<ScenarioOut[]>(mockScenarios(comparison))
      : HttpResponse.json(NO_COMPARISON, { status: 404 });
  }),
  // 假問答：不存檔；固定回一段說明，附推薦方案的一條條文
  http.post("*/api/v1/comparisons/:id/questions", async ({ params }) => {
    const rec = mockComparisons.get(String(params.id))?.recommendation;
    if (!rec) return HttpResponse.json(NO_COMPARISON, { status: 404 });
    await delay(300);
    return HttpResponse.json<QuestionAnswerOut>({
      answer: "可能適用：依條款，符合條件時在額度內給付。（假回答）",
      original_only: false,
      citations: [
        {
          plan_code: rec.recommended.plan_code,
          plan_name: rec.recommended.name,
          recommended: true,
          citations: [MOCK_CITATION],
        },
        {
          plan_code: rec.alternative.plan_code,
          plan_name: rec.alternative.name,
          recommended: false,
          citations: [],
        },
      ],
    });
  }),
  http.post("*/api/v1/auth/logout", () => {
    saveUser(null);
    return new HttpResponse(null, { status: 204 });
  }),
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
    HttpResponse.json<IngestJobDetail>({
      ...MOCK_JOB,
      events: MOCK_EVENTS.slice(0, 1),
      articles: [],
    }),
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
