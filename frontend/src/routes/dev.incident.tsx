import { Button } from "@base-ui/react/button";
import { createFileRoute, Link } from "@tanstack/react-router";
import { type FormEvent, type MouseEvent, useCallback, useEffect, useState } from "react";
import {
  authMe,
  createIncident,
  createSamplePolicy,
  getIncident,
  getIncidentPackage,
  listIncidents,
  listPolicies,
  patchIncidentTodo,
  sendIncidentMessage,
  submitIncident,
} from "../client";
import type {
  ClaimPackage,
  DocumentOut,
  IncidentContext,
  IncidentReply,
  IncidentSummaryOut,
  PolicyOut,
  SubmissionOut,
} from "../client/types.gen";
import { GoogleAuthResult } from "../features/google/GoogleAuthResult";
import { GoogleConsentDialog } from "../features/google/GoogleConsentDialog";
import type { GooglePurpose } from "../features/google/google";
import { useGoogleGrant } from "../features/google/useGoogleGrant";

type IncidentSearch = { incident?: string };

export const Route = createFileRoute("/dev/incident")({
  // incident：Google 授權完導回時，自動打開原本的事件
  validateSearch: (search: Record<string, unknown>): IncidentSearch => ({
    incident: typeof search.incident === "string" ? search.incident : undefined,
  }),
  component: IncidentPage,
});

const PHASE_LABEL = { on_site: "事故當下", after_return: "回家後" } as const;
const DOC_STATUS: Record<string, string> = {
  pending: "等待辨識",
  recognized: "辨識通過",
  needs_review: "需人工確認",
  failed: "失敗",
};

/** 後端的錯誤訊息：502 是 agent 的回傳不符合契約，訊息會指出是哪一條，原樣顯示給開發者看。 */
function detailOf(error: unknown, status?: number): string {
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  if (typeof detail === "string") return `${status ?? ""} ${detail}`.trim();
  if (Array.isArray(detail)) return `${status ?? 422} 請求格式不正確`;
  return `HTTP ${status ?? "無回應"}`;
}

const box = "space-y-2 rounded-md border p-3";
const input = "rounded-md border px-2 py-1";
const primary = "rounded-md bg-gray-900 px-3 py-1 text-white disabled:opacity-50";
const secondary = "rounded-md border px-3 py-1 hover:bg-gray-100 disabled:opacity-50";

/**
 * 事件流程測試台：保單 → 事件 → 5 釐清 → 勾選待辦 → 6 上傳文件 → 7 送件。
 * 給 5、6、7 號 agent 的負責人用（ADR-0015）：用目前設定的實作（預設是假實作）走完整條流程，
 * 契約被違反時會直接顯示後端回的 502 訊息。需要先登入；沒有保單可以按「建立範例保單」。
 */
function IncidentPage() {
  const [loggedIn, setLoggedIn] = useState<boolean | null>(null);
  const [policies, setPolicies] = useState<PolicyOut[]>([]);
  const [incidents, setIncidents] = useState<IncidentSummaryOut[]>([]);
  const [policyId, setPolicyId] = useState("");
  const [ctx, setCtx] = useState<IncidentContext | null>(null);
  const [reply, setReply] = useState<IncidentReply | null>(null);
  const [documents, setDocuments] = useState<DocumentOut[]>([]);
  const [pkg, setPkg] = useState<ClaimPackage | null>(null);
  const [submission, setSubmission] = useState<SubmissionOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Google 登入的使用者才要授權 Drive、Gmail（ADR-0020）；測試登入維持原本的流程
  const [googleUser, setGoogleUser] = useState(false);
  const grant = useGoogleGrant(googleUser);
  const [consent, setConsent] = useState<GooglePurpose | null>(null);
  const { incident: incidentFromUrl } = Route.useSearch();

  const refreshLists = useCallback(async () => {
    const me = await authMe();
    if (me.response?.status === 401) {
      setLoggedIn(false);
      return;
    }
    setLoggedIn(true);
    setGoogleUser(me.data?.login_provider === "google");
    const [p, i] = await Promise.all([listPolicies(), listIncidents()]);
    if (p.data) {
      setPolicies(p.data);
      setPolicyId((current) => current || p.data?.[0]?.id || "");
    }
    if (i.data) setIncidents(i.data);
  }, []);

  useEffect(() => {
    void refreshLists();
  }, [refreshLists]);

  // Google 授權完導回（?incident=<id>）：打開原本的事件
  // biome-ignore lint/correctness/useExhaustiveDependencies: 只依網址打開一次，run、open 每次 render 都是新的
  useEffect(() => {
    if (incidentFromUrl) void run(() => open(incidentFromUrl));
  }, [incidentFromUrl]);

  /** 授權完要回到的頁面：目前的事件。 */
  const backHere = ctx ? `/dev/incident?incident=${ctx.incident_id}` : "/dev/incident";

  /**
   * 這次動作需要哪個授權還沒有：null 代表都可以用（或不是 Google 登入，不用授權）；
   * "checking" 代表還在向 Google 確認，先別動作。
   */
  function missingGrant(needs: GooglePurpose[]): GooglePurpose | "checking" | null {
    if (!googleUser) return null;
    if (!grant.data) return "checking";
    return needs.find((purpose) => !grant.data[purpose]) ?? null;
  }

  /** 缺授權時：還在確認就請使用者稍等，否則先說明並請使用者授權。回傳是否要擋下這次動作。 */
  function blockedByGrant(needs: GooglePurpose[]): boolean {
    const missing = missingGrant(needs);
    if (missing === "checking") {
      setNotice("正在確認 Google 授權，請稍候再按一次。");
      return true;
    }
    if (missing) {
      setConsent(missing);
      return true;
    }
    return false;
  }

  /** 按「選擇檔案」：Drive 不能用時擋下選檔視窗，先說明並請使用者授權（授權會整頁跳走，選好的檔案會不見）。 */
  const chooseFile = (e: MouseEvent<HTMLInputElement>) => {
    if (blockedByGrant(["drive"])) e.preventDefault();
  };

  /** 包住所有動作：統一處理忙碌狀態與錯誤顯示。 */
  async function run(action: () => Promise<void>) {
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function open(id: string) {
    const res = await getIncident({ path: { incident_id: id } });
    if (!res.data) throw new Error(detailOf(res.error, res.response?.status));
    setCtx(res.data);
    setPkg(null);
    setSubmission(null);
  }

  const sampleAction = () =>
    run(async () => {
      const res = await createSamplePolicy();
      if (!res.data) throw new Error(detailOf(res.error, res.response?.status));
      setNotice(res.data.message);
      setPolicyId(res.data.policy_id);
      await refreshLists();
    });

  const startAction = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    return run(async () => {
      const res = await createIncident({
        path: { policy_id: policyId },
        body: {
          description: String(form.get("description")),
          destination: String(form.get("destination") || "") || null,
        },
      });
      if (!res.data) throw new Error(detailOf(res.error, res.response?.status));
      setCtx(res.data.incident);
      setReply(res.data.reply);
      setDocuments([]);
      setPkg(null);
      setSubmission(null);
      await refreshLists();
    });
  };

  const sendAction = (text: string, mode: "text" | "quick_reply") =>
    run(async () => {
      if (!ctx) return;
      const res = await sendIncidentMessage({
        path: { incident_id: ctx.incident_id },
        body: { content: text, input_mode: mode },
      });
      if (!res.data) throw new Error(detailOf(res.error, res.response?.status));
      setCtx(res.data.incident);
      setReply(res.data.reply);
    });

  const toggleTodo = (todoId: string, isDone: boolean) =>
    run(async () => {
      if (!ctx) return;
      const res = await patchIncidentTodo({
        path: { incident_id: ctx.incident_id, todo_id: todoId },
        body: { is_done: isDone },
      });
      if (!res.data) throw new Error(detailOf(res.error, res.response?.status));
      setCtx(res.data);
    });

  const uploadAction = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const formEl = e.currentTarget;
    const data = new FormData(formEl);
    return run(async () => {
      if (!ctx) return;
      const response = await fetch(`/api/v1/incidents/${ctx.incident_id}/documents`, {
        method: "POST",
        body: data,
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(detailOf(body, response.status));
      setDocuments((current) => [body as DocumentOut, ...current]);
      formEl.reset();
      await open(ctx.incident_id);
    });
  };

  const packageAction = () =>
    run(async () => {
      if (!ctx) return;
      const res = await getIncidentPackage({ path: { incident_id: ctx.incident_id } });
      if (!res.data) throw new Error(detailOf(res.error, res.response?.status));
      setPkg(res.data);
    });

  const submitAction = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!allDone) {
      // 還缺文件：要先上傳，所以 Drive 不能用就先授權 Drive（還不需要 Gmail）；
      // Drive 可以用就照原本的流程讓後端擋下，並帶使用者回到上傳文件
      if (blockedByGrant(["drive"])) return;
      document.getElementById("upload-section")?.scrollIntoView({ behavior: "smooth" });
    } else if (blockedByGrant(["drive", "gmail"])) {
      // 文件備齊：寄信要從 Drive 讀附件，先確認 Drive，再確認 Gmail
      return;
    }
    const recipient = String(new FormData(e.currentTarget).get("recipient"));
    return run(async () => {
      if (!ctx) return;
      const res = await submitIncident({
        path: { incident_id: ctx.incident_id },
        body: { recipient },
      });
      if (!res.data) throw new Error(detailOf(res.error, res.response?.status));
      setSubmission(res.data);
      await open(ctx.incident_id);
      await refreshLists();
    });
  };

  if (loggedIn === false) {
    return (
      <p>
        要先登入才能試事件流程。
        <Link to="/login" search={{ next: "/dev/incident" }} className="underline">
          前往登入
        </Link>
        （開發環境有測試登入）。
      </p>
    );
  }

  const allDone = !!ctx && ctx.todos?.length !== 0 && ctx.todos?.every((t) => t.is_done);

  return (
    <section className="space-y-4">
      <p className="text-gray-600">
        用目前設定的 agent 實作（<code>AGENT_5／6／7_IMPL</code>，預設是假實作）走完整條流程。
        契約被違反時會看到後端回的 502 與是哪一條。
      </p>
      {error && (
        <p role="alert" className="rounded-md bg-red-50 p-2 text-red-800" data-testid="error">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="rounded-md bg-green-50 p-2 text-green-800">
          {notice}
        </p>
      )}
      <GoogleAuthResult />
      {googleUser && (
        <p className="text-sm text-gray-600" data-testid="dev-google-status">
          Google 授權：Drive {grant.data?.drive ? "可以使用" : "未授權"}、Gmail{" "}
          {grant.data?.gmail ? "可以使用" : "未授權"}
        </p>
      )}
      <GoogleConsentDialog purpose={consent} next={backHere} onClose={() => setConsent(null)} />

      <div className="grid gap-4 md:grid-cols-[20rem_1fr]">
        <aside className="space-y-4">
          <div className={box}>
            <h2 className="font-bold">1. 保單與事件</h2>
            <label className="block space-y-1">
              <span className="block text-sm font-medium">保單</span>
              <select
                value={policyId}
                onChange={(e) => setPolicyId(e.target.value)}
                className={`${input} w-full`}
                data-testid="policy"
              >
                {policies.length === 0 && <option value="">（還沒有保單）</option>}
                {policies.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.display_name}
                  </option>
                ))}
              </select>
            </label>
            <Button
              type="button"
              onClick={sampleAction}
              disabled={busy}
              className={secondary}
              data-testid="sample-policy"
            >
              建立範例保單
            </Button>
            <form onSubmit={startAction} className="space-y-2" data-testid="start-form">
              <label className="block space-y-1">
                <span className="block text-sm font-medium">發生了什麼事</span>
                <textarea
                  name="description"
                  required
                  rows={2}
                  defaultValue="班機延誤了六小時"
                  className={`${input} w-full`}
                />
              </label>
              <label className="block space-y-1">
                <span className="block text-sm font-medium">目的地</span>
                <input name="destination" defaultValue="日本" className={`${input} w-full`} />
              </label>
              <Button
                type="submit"
                disabled={busy || !policyId}
                className={primary}
                data-testid="start"
              >
                開始事件
              </Button>
            </form>
          </div>

          <div className={box}>
            <h2 className="font-bold">我的事件</h2>
            <ul className="space-y-1" data-testid="incidents">
              {incidents.length === 0 && <li className="text-gray-500">還沒有事件</li>}
              {incidents.map((i) => (
                <li key={i.id}>
                  <button
                    type="button"
                    onClick={() => void run(() => open(i.id))}
                    className={`w-full rounded-md border px-2 py-1 text-left hover:bg-gray-100 ${
                      ctx?.incident_id === i.id ? "bg-gray-100" : ""
                    }`}
                  >
                    {i.title}
                    <span className="block text-xs text-gray-500">
                      {i.incident_type_name ?? "類型未定"} ·{" "}
                      {i.status === "completed" ? "已完成" : "進行中"}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </aside>

        {!ctx ? (
          <p className="text-gray-500">選一個事件，或建立新的事件。</p>
        ) : (
          <div className="space-y-4" data-testid="incident">
            <div className={box}>
              <h2 className="text-lg font-bold" data-testid="incident-title">
                {ctx.title}
              </h2>
              <p className="text-sm text-gray-600">
                {ctx.incident_type_name ?? "類型未定"} ·{" "}
                {ctx.status === "completed" ? "已完成" : "進行中"}
                {" · "}
                {ctx.policy.plan_name}
                {ctx.policy.sum_insured != null &&
                  ` · 保額 ${ctx.policy.sum_insured.toLocaleString()}`}
              </p>
            </div>

            <div className={box}>
              <h2 className="font-bold">2. 和 5 號 agent 對話</h2>
              <ol className="space-y-1" data-testid="messages">
                {ctx.messages?.map((m, i) => (
                  <li
                    // biome-ignore lint/suspicious/noArrayIndexKey: 訊息沒有穩定 id，順序固定
                    key={i}
                    className={m.role === "user" ? "text-right" : ""}
                  >
                    <span
                      className={`inline-block rounded-md px-2 py-1 ${
                        m.role === "user" ? "bg-gray-900 text-white" : "bg-gray-100"
                      }`}
                    >
                      {m.content}
                    </span>
                  </li>
                ))}
              </ol>
              {reply?.quick_replies && reply.quick_replies.length > 0 && (
                <div className="flex flex-wrap gap-2" data-testid="quick-replies">
                  {reply.quick_replies.map((q) => (
                    <Button
                      key={q}
                      type="button"
                      disabled={busy}
                      onClick={() => sendAction(q, "quick_reply")}
                      className={secondary}
                    >
                      {q}
                    </Button>
                  ))}
                </div>
              )}
              {reply?.citations && reply.citations.length > 0 && (
                <p className="text-sm text-gray-600" data-testid="citations">
                  出處：
                  {reply.citations
                    .map((c) => `${c.insurance_code} 第 ${c.article_no} 條`)
                    .join("、")}
                </p>
              )}
              <form
                className="flex gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  const form = e.currentTarget;
                  const text = String(new FormData(form).get("content"));
                  form.reset();
                  void sendAction(text, "text");
                }}
              >
                <input
                  name="content"
                  required
                  placeholder="說一句話…"
                  aria-label="訊息"
                  className={`${input} flex-1`}
                  data-testid="message"
                />
                <Button type="submit" disabled={busy} className={primary} data-testid="send">
                  送出
                </Button>
              </form>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <div className={box}>
                <h2 className="font-bold">事件狀況</h2>
                <ul className="space-y-1" data-testid="facts">
                  {ctx.facts?.length === 0 && <li className="text-gray-500">還沒有</li>}
                  {ctx.facts?.map((f) => (
                    <li key={f.fact_key}>
                      <span className="font-medium">{f.label}：</span>
                      {f.value}
                    </li>
                  ))}
                </ul>
                <h2 className="pt-2 font-bold">適用的保障（{ctx.clauses?.length ?? 0}）</h2>
                <ul className="max-h-40 space-y-1 overflow-y-auto text-sm" data-testid="clauses">
                  {ctx.clauses?.map((c) => (
                    <li key={`${c.insurance_code}|${c.section ?? ""}|${c.subsection ?? ""}`}>
                      <code>{c.insurance_code}</code> {c.section ?? "整份"}
                      {c.subsection && ` ${c.subsection}`}
                      {c.reason && <span className="text-gray-500">（{c.reason}）</span>}
                    </li>
                  ))}
                </ul>
              </div>

              <div className={box}>
                <h2 className="font-bold">3. 待辦</h2>
                <ul className="space-y-1" data-testid="todos">
                  {ctx.todos?.map((t) => (
                    <li key={t.id}>
                      <label className="flex items-start gap-2">
                        <input
                          type="checkbox"
                          checked={t.is_done ?? false}
                          disabled={busy}
                          onChange={(e) => void toggleTodo(t.id, e.target.checked)}
                          className="mt-1.5"
                        />
                        <span>
                          {t.title}
                          <span className="block text-xs text-gray-500">
                            {PHASE_LABEL[t.phase]}
                            {t.done_by &&
                              ` · ${t.done_by === "agent" ? "系統判斷完成" : "使用者勾選"}`}
                            {t.note && ` · ${t.note}`}
                          </span>
                        </span>
                      </label>
                    </li>
                  ))}
                </ul>
              </div>
            </div>

            <div className={box} id="upload-section">
              <h2 className="font-bold">4. 上傳文件（6 號 agent）</h2>
              <form onSubmit={uploadAction} className="flex flex-wrap items-end gap-2">
                <input
                  type="file"
                  name="file"
                  required
                  aria-label="文件"
                  onClick={chooseFile}
                  data-testid="doc-file"
                />
                <Button type="submit" disabled={busy} className={primary} data-testid="upload">
                  上傳並辨識
                </Button>
              </form>
              <p className="text-xs text-gray-500">
                假實作依檔名判斷：含「診斷」「證明」「收據」會辨識通過並勾選第一個未完成的待辦；含
                bad 會失敗；其他需人工確認。
              </p>
              <ul className="space-y-1 text-sm" data-testid="documents">
                {documents.map((d) => (
                  <li key={d.id}>
                    {d.file_name} → {DOC_STATUS[d.recognition_status] ?? d.recognition_status}
                    {d.document_kind && `（${d.document_kind}）`}
                    {d.reason && <span className="text-gray-500"> · {d.reason}</span>}
                  </li>
                ))}
                {ctx.documents
                  ?.filter((d) => !documents.some((x) => x.id === d.id))
                  .map((d) => (
                    <li key={d.id}>
                      {d.file_name} → {DOC_STATUS[d.recognition_status] ?? d.recognition_status}
                    </li>
                  ))}
              </ul>
            </div>

            <div className={box}>
              <h2 className="font-bold">5. 送件（7 號 agent）</h2>
              <p className="text-sm text-gray-600" data-testid="all-done">
                {allDone ? "所有待辦都完成了，可以送件。" : "還有待辦沒完成，送件會被擋下（409）。"}
              </p>
              <Button
                type="button"
                onClick={packageAction}
                disabled={busy}
                className={secondary}
                data-testid="package"
              >
                預覽送件包
              </Button>
              {pkg && (
                <div
                  className="space-y-1 rounded-md bg-gray-50 p-2 text-sm"
                  data-testid="package-view"
                >
                  <p className="font-medium">{pkg.subject}</p>
                  <pre className="whitespace-pre-wrap">{pkg.body}</pre>
                  <p>附件：{pkg.attachments?.map((a) => a.file_name).join("、") || "（無）"}</p>
                  {(pkg.missing_todo_ids?.length ?? 0) > 0 && (
                    <p className="text-red-700">還缺 {pkg.missing_todo_ids?.length} 個待辦</p>
                  )}
                </div>
              )}
              <form onSubmit={submitAction} className="flex flex-wrap gap-2">
                <input
                  name="recipient"
                  type="email"
                  required
                  defaultValue={pkg?.recipient_hint ?? "claims@example.com"}
                  key={pkg?.recipient_hint ?? "default"}
                  aria-label="收件人"
                  className={`${input} flex-1`}
                  data-testid="recipient"
                />
                <Button type="submit" disabled={busy} className={primary} data-testid="submit">
                  送件
                </Button>
              </form>
              {submission && (
                <p
                  className={submission.status === "sent" ? "text-green-800" : "text-red-700"}
                  data-testid="submission"
                >
                  {submission.status === "sent" ? "已寄出" : "寄送失敗"}
                  {submission.external_ref && `（${submission.external_ref}）`}
                  {submission.reason && ` ${submission.reason}`}
                </p>
              )}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
