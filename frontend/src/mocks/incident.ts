import { HttpResponse, http } from "msw";
import type {
  ClaimPackage,
  CreateIncidentIn,
  DocumentOut,
  DocumentView,
  IncidentContext,
  IncidentReply,
  IncidentReplyOut,
  IncidentSummaryOut,
  ManualPolicyIn,
  PlanSumInsuredOptionsOut,
  PolicyOut,
  SubmissionOut,
  TodoView,
} from "../client/types.gen";

// 出事了流程（保單 → 事件 → 待辦 → 文件 → 送件）的假資料，行為照後端的假 agent：
// 開始事件先問一個問題 → 再回答一次才判斷出「班機延誤」並產生待辦 → 檔名含「證明」「收據」「診斷」才辨識通過。
// 狀態存在記憶體，重新整理就回到最初；最初有兩個事件：「可送件」與「已完成」，直接看得到後面兩個步驟。

const uuid = (n: number) => `00000000-0000-0000-0000-${String(n).padStart(12, "0")}`;
let seq = 100;
const nextId = () => uuid(++seq);

const POLICY_COVERAGE = { plan_id: "fubon_advanced", plan_name: "富邦國外旅平險-進階型（假資料）" };

const BASE_POLICY: PolicyOut = {
  id: uuid(1),
  display_name: "富邦國外旅平險-進階型（假資料） 2026-11-01 10:00",
  plan_id: POLICY_COVERAGE.plan_id,
  plan_name: POLICY_COVERAGE.plan_name,
  sum_insured: 6_000_000,
  start_date: "2026-11-01",
  end_date: "2026-11-05",
  insurances: [{ code: "FUBON01", name: "旅行平安保險" }],
  addons: [],
  created_at: "2026-11-01T02:00:00Z",
};

const policies: PolicyOut[] = [BASE_POLICY];

function summaryOf(p: PolicyOut): IncidentContext["policy"] {
  return {
    plan_id: p.plan_id,
    plan_name: p.plan_name,
    sum_insured: p.sum_insured,
    start_date: p.start_date,
    end_date: p.end_date,
    insurance_codes: p.insurances.map((i) => i.code),
    coverages: p.insurances.map((i) => ({ insurance_code: i.code, section: null })),
  };
}

const todo = (n: number, title: string, requiresUpload: boolean, done = false): TodoView => ({
  id: uuid(900 + n),
  phase: "after_return",
  title,
  is_done: done,
  status: done ? "done" : "pending",
  done_by: done ? "agent" : null,
  sort_order: n,
  scope: "incident",
  requires_upload: requiresUpload,
});

const flightDelayTodos = (done: boolean): TodoView[] => [
  todo(1, "理賠申請書", true, done),
  todo(2, "機票及登機證，或航空業者出具的搭機證明", true, done),
  todo(3, "航空業者出具、載有班機延誤期間的證明", true, done),
];

type MockIncident = {
  ctx: IncidentContext;
  createdAt: string;
  /** 使用者回答過幾次：0 = 剛建立，1 = 已回答第一題，2 以上 = 類型已判斷 */
  answers: number;
  sent: boolean;
};

function newIncident(id: string, policy: PolicyOut, body: CreateIncidentIn): MockIncident {
  return {
    createdAt: new Date().toISOString(),
    answers: 0,
    sent: false,
    ctx: {
      incident_id: id,
      title: body.title ?? "事件處理中",
      description: body.description,
      status: "open",
      destination: body.destination ?? null,
      policy: summaryOf(policy),
      messages: [
        { role: "user", content: body.description },
        { role: "assistant", content: "發生在哪一天、哪個機場？（假資料）" },
      ],
      todos: [],
      facts: [],
      clauses: [],
      documents: [],
      major_notices: [],
    },
  };
}

const incidents = new Map<string, MockIncident>();
{
  const ready = newIncident(uuid(50), BASE_POLICY, { description: "班機延誤了六小時" });
  ready.answers = 2;
  ready.ctx = {
    ...ready.ctx,
    title: "班機延誤（可送件）",
    incident_type_code: "flight_delay",
    incident_type_name: "班機延誤",
    todos: flightDelayTodos(true),
    major_notices: ["請在回國後 30 天內送件。（假資料）"],
    facts: [{ fact_key: "airport", label: "機場", value: "東京成田機場" }],
    clauses: [
      { insurance_code: "FUBON01", section: "第一章 共同條款", reason: "班機延誤（假資料）" },
    ],
  };
  incidents.set(uuid(50), ready);
  const done = newIncident(uuid(51), BASE_POLICY, { description: "行李遺失" });
  done.answers = 2;
  done.sent = true;
  done.ctx = {
    ...done.ctx,
    title: "行李遺失（已完成）",
    status: "completed",
    incident_type_code: "baggage_loss",
    incident_type_name: "行李遺失",
    todos: flightDelayTodos(true),
  };
  incidents.set(uuid(51), done);
}

const summary = (id: string, m: MockIncident): IncidentSummaryOut => ({
  id,
  title: m.ctx.title,
  status: m.ctx.status,
  incident_type_name: m.ctx.incident_type_name ?? null,
  created_at: m.createdAt,
});

const notFound = () => HttpResponse.json({ detail: "找不到這個事件" }, { status: 404 });
// 結案後鎖住（#152）：會修改事件的 API 回 409
const closedError = () => HttpResponse.json({ detail: "事件已結案，不能修改" }, { status: 409 });
const pending = (ctx: IncidentContext) =>
  ctx.todos?.filter((t) => !t.is_done && t.status !== "not_applicable") ?? [];

/** 使用者回答一次：第一次追問、第二次判斷出類型。 */
function advance(m: MockIncident, content: string): IncidentReply {
  m.answers += 1;
  m.ctx.messages = [...(m.ctx.messages ?? []), { role: "user", content }];
  if (m.answers === 1) {
    const reply = { message: "目前人在哪裡？（假資料）", quick_replies: ["在機場", "已回國"] };
    m.ctx.messages.push({ role: "assistant", content: reply.message });
    return reply;
  }
  const reply: IncidentReply = {
    message: "判斷是班機延誤，已整理好需要準備的文件。（假資料）",
    citations: [{ insurance_code: "FUBON01", article_no: 23 }],
    finished: true,
  };
  m.ctx = {
    ...m.ctx,
    title: "班機延誤",
    incident_type_code: "flight_delay",
    incident_type_name: "班機延誤",
    todos: flightDelayTodos(false),
    facts: [{ fact_key: "airport", label: "機場", value: content }],
    clauses: [
      { insurance_code: "FUBON01", section: "第一章 共同條款", reason: "班機延誤（假資料）" },
    ],
    major_notices: ["請在回國後 30 天內送件。（假資料）"],
    messages: [...(m.ctx.messages ?? []), { role: "assistant", content: reply.message }],
  };
  return reply;
}

const RECOGNIZED = /證明|收據|診斷/;

export const incidentHandlers = [
  http.get("*/api/v1/policies", () => HttpResponse.json<PolicyOut[]>([...policies].reverse())),
  http.post("*/api/v1/policies", () => {
    const policy: PolicyOut = {
      ...BASE_POLICY,
      id: nextId(),
      created_at: new Date().toISOString(),
    };
    policies.push(policy);
    return HttpResponse.json<PolicyOut>(policy, { status: 201 });
  }),
  http.post("*/api/v1/policies/manual", async ({ request }) => {
    const body = (await request.json()) as ManualPolicyIn;
    const policy: PolicyOut = {
      ...BASE_POLICY,
      id: nextId(),
      display_name: `${body.plan_id} ${new Date().toISOString().slice(0, 16).replace("T", " ")}`,
      plan_id: body.plan_id,
      plan_name: POLICY_COVERAGE.plan_name,
      sum_insured: body.sum_insured,
      start_date: body.start_date ?? null,
      end_date: body.end_date ?? null,
      created_at: new Date().toISOString(),
    };
    policies.push(policy);
    return HttpResponse.json<PolicyOut>(policy, { status: 201 });
  }),
  http.get("*/api/v1/plans/:planId/sum-insured-options", ({ params }) =>
    HttpResponse.json<PlanSumInsuredOptionsOut>({
      plan_id: String(params.planId),
      sum_insured: [6_000_000, 8_000_000, 10_000_000],
    }),
  ),

  http.get("*/api/v1/incidents", () =>
    HttpResponse.json<IncidentSummaryOut[]>(
      [...incidents].map(([id, m]) => summary(id, m)).reverse(),
    ),
  ),
  http.post("*/api/v1/policies/:policyId/incidents", async ({ params, request }) => {
    const policy = policies.find((p) => p.id === params.policyId);
    if (!policy) return HttpResponse.json({ detail: "找不到這份保單" }, { status: 404 });
    const body = (await request.json()) as CreateIncidentIn;
    const id = nextId();
    const m = newIncident(id, policy, body);
    incidents.set(id, m);
    const reply: IncidentReply = {
      message: m.ctx.messages?.[1]?.content ?? "",
      quick_replies: ["在機場", "已回國"],
    };
    return HttpResponse.json<IncidentReplyOut>({ reply, incident: m.ctx }, { status: 201 });
  }),
  http.get("*/api/v1/incidents/:id", ({ params }) => {
    const m = incidents.get(String(params.id));
    return m ? HttpResponse.json<IncidentContext>(m.ctx) : notFound();
  }),
  http.post("*/api/v1/incidents/:id/messages", async ({ params, request }) => {
    const m = incidents.get(String(params.id));
    if (!m) return notFound();
    if (m.ctx.status === "completed") return closedError();
    const { content } = (await request.json()) as { content: string };
    const reply = advance(m, content);
    return HttpResponse.json<IncidentReplyOut>({ reply, incident: m.ctx });
  }),
  http.patch("*/api/v1/incidents/:id/todos/:todoId", async ({ params, request }) => {
    const m = incidents.get(String(params.id));
    if (!m) return notFound();
    if (m.ctx.status === "completed") return closedError();
    const { is_done } = (await request.json()) as { is_done: boolean };
    m.ctx.todos = m.ctx.todos?.map((t) =>
      t.id === params.todoId
        ? {
            ...t,
            is_done,
            status: is_done ? "done" : "pending",
            done_by: is_done ? "user" : null,
            without_document: is_done && !!t.requires_upload,
          }
        : t,
    );
    return HttpResponse.json<IncidentContext>(m.ctx);
  }),
  http.post("*/api/v1/incidents/:id/documents", async ({ params, request }) => {
    const m = incidents.get(String(params.id));
    if (!m) return notFound();
    if (m.ctx.status === "completed") return closedError();
    const file = (await request.formData()).get("file") as File;
    const recognized = RECOGNIZED.test(file.name);
    const target = pending(m.ctx).find((t) => t.requires_upload);
    const doc: DocumentView = {
      id: nextId(),
      todo_id: recognized ? (target?.id ?? null) : null,
      file_name: file.name,
      content_type: file.type || "application/octet-stream",
      storage_path: `mock/${file.name}`,
      recognition_status: recognized ? "recognized" : "needs_review",
      document_kind: recognized ? "證明文件" : null,
    };
    m.ctx.documents = [...(m.ctx.documents ?? []), doc];
    if (recognized && target) {
      m.ctx.todos = m.ctx.todos?.map((t) =>
        t.id === target.id ? { ...t, is_done: true, status: "done", done_by: "agent" } : t,
      );
    }
    return HttpResponse.json<DocumentOut>(
      {
        id: doc.id,
        file_name: doc.file_name,
        recognition_status: doc.recognition_status,
        document_kind: doc.document_kind ?? null,
        todo_id: doc.todo_id ?? null,
        reason: recognized ? null : "無法確定是哪一份文件，請你確認（假資料）",
      },
      { status: 201 },
    );
  }),
  http.post("*/api/v1/incidents/:id/documents/:docId/confirm", async ({ params, request }) => {
    const m = incidents.get(String(params.id));
    if (!m) return notFound();
    if (m.ctx.status === "completed") return closedError();
    const { todo_id } = (await request.json()) as { todo_id: string };
    m.ctx.documents = m.ctx.documents?.map((d) =>
      d.id === params.docId ? { ...d, todo_id, confirmed_by_user: true } : d,
    );
    m.ctx.todos = m.ctx.todos?.map((t) =>
      t.id === todo_id ? { ...t, is_done: true, status: "done", done_by: "user" } : t,
    );
    return HttpResponse.json<IncidentContext>(m.ctx);
  }),
  http.get("*/api/v1/incidents/:id/package", ({ params }) => {
    const m = incidents.get(String(params.id));
    if (!m) return notFound();
    return HttpResponse.json<ClaimPackage>({
      subject: `${m.ctx.title} 理賠申請（假資料）`,
      body: "您好，我是（請填寫被保險人姓名），保單號碼（請填寫保單號碼）。附上班機延誤的理賠文件，請協助處理。（假資料）",
      attachments: (m.ctx.documents ?? []).map((d) => ({
        document_id: d.id,
        file_name: d.file_name,
        storage_path: d.storage_path,
      })),
      missing_todo_ids: pending(m.ctx).map((t) => t.id),
      recipient_hint: "claims@example.com",
    });
  }),
  http.post("*/api/v1/incidents/:id/submission", async ({ params, request }) => {
    const m = incidents.get(String(params.id));
    if (!m) return notFound();
    if (m.ctx.status === "completed") return closedError();
    if (pending(m.ctx).length > 0) {
      return HttpResponse.json({ detail: "還有待辦沒完成，不能送件" }, { status: 409 });
    }
    const body = (await request.json()) as {
      mode?: "send" | "draft" | "self";
      fills?: Record<string, string>;
      recipient?: string | null;
    };
    const mode = body.mode ?? "send";
    if (mode === "send") {
      // 和後端一致：寄出時還有空格就擋下並列出項目
      const left = ["被保險人姓名", "保單號碼"].filter((item) => !body.fills?.[item]?.trim());
      if (left.length > 0) {
        return HttpResponse.json(
          { detail: `信裡還有要填寫的項目：${left.join("、")}，填完才能寄出` },
          { status: 409 },
        );
      }
    }
    m.sent = true;
    m.ctx.status = "completed";
    const status = mode === "send" ? "sent" : mode === "draft" ? "drafted" : "self_submitted";
    return HttpResponse.json<SubmissionOut>(
      {
        id: nextId(),
        status,
        external_ref: mode === "self" ? null : `mock-${mode}-id`,
        reason: null,
      },
      { status: 201 },
    );
  }),
];
