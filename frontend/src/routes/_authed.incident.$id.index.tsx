import { Button } from "@base-ui/react/button";
import { createFileRoute, Link } from "@tanstack/react-router";
import { type FormEvent, useState } from "react";
import { patchIncidentTodo, sendIncidentMessage } from "../client";
import { ClarifyingView } from "../features/incident/ClarifyingView";
import {
  box,
  errorText,
  input,
  primary,
  secondary,
  useIncident,
} from "../features/incident/shared";

export const Route = createFileRoute("/_authed/incident/$id/")({
  component: IncidentHome,
});

const PHASE_LABEL = { on_site: "事故當下", after_return: "回家後" } as const;

/** 還在追問時是 2-2 描述事故；問完（有事故類型）才是理賠頁（2-3）。 */
function IncidentHome() {
  const { id } = Route.useParams();
  const { data: ctx } = useIncident(id);
  if (!ctx) return null;
  if (!ctx.incident_type_code && ctx.status !== "completed") {
    return <ClarifyingView id={id} ctx={ctx} />;
  }
  return <ChatStep />;
}

/** 步驟 1：和助理說明狀況，並勾選待辦。 */
function ChatStep() {
  const { id } = Route.useParams();
  const { data: ctx, setIncident, refresh } = useIncident(id);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 系統已確認的待辦被取消勾選前，先問一次
  const [undoing, setUndoing] = useState<string | null>(null);

  if (!ctx) return null;

  const messages = ctx.messages ?? [];
  // 快速選項只在最後一則是 5 號的訊息時顯示：旅客已經回答過的舊問題，選項不再出現
  const last = messages.at(-1);
  const quickReplies = last?.role === "assistant" ? (last.quick_replies ?? []) : [];

  async function send(text: string, mode: "text" | "quick_reply") {
    setBusy(true);
    setError(null);
    const res = await sendIncidentMessage({
      path: { incident_id: id },
      body: { content: text, input_mode: mode },
    });
    setBusy(false);
    if (!res.data) return setError(errorText(res.error, res.response?.status));
    // 5 號回覆可能很慢，期間使用者可能已在別頁上傳文件或勾了待辦：
    // 回應裡的事件是送出當下的快照，不能直接蓋掉快取，改成重新讀取。
    // 快速選項與出處也從重新讀到的 ctx.messages 來，重新整理後才會還原（#212）
    await refresh();
  }

  async function toggle(todoId: string, isDone: boolean) {
    setBusy(true);
    setError(null);
    setUndoing(null);
    const res = await patchIncidentTodo({
      path: { incident_id: id, todo_id: todoId },
      body: { is_done: isDone },
    });
    setBusy(false);
    if (!res.data) return setError(errorText(res.error, res.response?.status));
    setIncident(res.data);
  }

  const onSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = e.currentTarget;
    const text = String(new FormData(form).get("content"));
    form.reset();
    void send(text, "text");
  };

  const todos = ctx.todos ?? [];
  // 結案後鎖住：後端會回 409，畫面直接停用（#152）
  const closed = ctx.status === "completed";

  return (
    <div className="space-y-4">
      {error && (
        <p role="alert" className="rounded-md bg-red-50 p-2 text-red-800" data-testid="error">
          {error}
        </p>
      )}
      <div className="grid gap-4 md:grid-cols-2">
        <section className={box} aria-label="對話">
          <h2 className="font-bold">說明狀況</h2>
          <ol className="space-y-1" data-testid="messages">
            {messages.map((m, i) => (
              <li
                // biome-ignore lint/suspicious/noArrayIndexKey: 訊息沒有穩定 id，順序固定
                key={i}
                className={m.role === "user" ? "text-right" : ""}
              >
                <span
                  className={`inline-block rounded-md px-2 py-1 text-left ${
                    m.role === "user" ? "bg-gray-900 text-white" : "bg-gray-100"
                  }`}
                >
                  {m.content}
                </span>
                {m.citations && m.citations.length > 0 && (
                  <p className="mt-0.5 text-sm text-gray-600" data-testid="citations">
                    依據：
                    {m.citations.map((c) => `${c.insurance_code} 第 ${c.article_no} 條`).join("、")}
                  </p>
                )}
              </li>
            ))}
          </ol>
          {quickReplies.length > 0 && (
            <div className="flex flex-wrap gap-2" data-testid="quick-replies">
              {quickReplies.map((q) => (
                <Button
                  key={q}
                  type="button"
                  disabled={busy || closed}
                  onClick={() => void send(q, "quick_reply")}
                  className={secondary}
                >
                  {q}
                </Button>
              ))}
            </div>
          )}
          <form className="flex gap-2" onSubmit={onSubmit}>
            <input
              name="content"
              required
              disabled={closed}
              placeholder="說一句話…"
              aria-label="訊息"
              className={`${input} min-w-0 flex-1`}
              data-testid="message"
            />
            <Button type="submit" disabled={busy || closed} className={primary} data-testid="send">
              送出
            </Button>
          </form>
        </section>

        <section className={box} aria-label="待辦">
          <h2 className="font-bold">待辦</h2>
          {todos.length === 0 && (
            <p className="text-sm text-gray-500">
              說明完狀況，助理確認事故類型後，這裡會列出需要準備的事。
            </p>
          )}
          <ul className="space-y-2" data-testid="todos">
            {todos.map((t) => (
              <li key={t.id}>
                <label className="flex items-start gap-2">
                  <input
                    type="checkbox"
                    checked={t.is_done ?? false}
                    disabled={busy || closed || t.status === "not_applicable"}
                    onChange={(e) =>
                      t.done_by === "agent" && !e.target.checked
                        ? setUndoing(t.id)
                        : void toggle(t.id, e.target.checked)
                    }
                    className="mt-1.5"
                  />
                  <span className="min-w-0">
                    {t.title}
                    <span className="block text-xs text-gray-500">
                      {PHASE_LABEL[t.phase]}
                      {t.status === "not_applicable" && " · 不適用"}
                      {t.done_by === "agent" && " · 系統確認"}
                      {t.done_by === "user" && " · 你勾選"}
                      {t.without_document && " · 未附文件"}
                      {t.requires_upload && !t.is_done && " · 需上傳文件"}
                      {t.note && ` · ${t.note}`}
                    </span>
                  </span>
                </label>
                {undoing === t.id && (
                  <p className="ml-6 space-x-2 text-sm" role="alert">
                    這項是系統看過你的文件後確認的，確定要取消？
                    <Button
                      type="button"
                      onClick={() => void toggle(t.id, false)}
                      className={secondary}
                    >
                      確定取消
                    </Button>
                    <Button type="button" onClick={() => setUndoing(null)} className={secondary}>
                      保留
                    </Button>
                  </p>
                )}
              </li>
            ))}
          </ul>
        </section>
      </div>

      {(ctx.major_notices?.length ?? 0) > 0 && (
        <section className={box} aria-label="重大注意事項">
          <h2 className="font-bold">重大注意事項</h2>
          <ul className="list-disc space-y-1 pl-5 text-sm" data-testid="major-notices">
            {ctx.major_notices?.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </section>
      )}

      <section className={box} aria-label="事件狀況與適用保障">
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
        <h2 className="pt-2 font-bold">可能適用的保障</h2>
        <ul className="space-y-1 text-sm" data-testid="clauses">
          {ctx.clauses?.length === 0 && <li className="text-gray-500">還沒有</li>}
          {ctx.clauses?.map((c) => (
            <li key={`${c.insurance_code}|${c.section ?? ""}`}>
              {c.insurance_code} {c.section ?? "整份"}
              {c.reason && <span className="text-gray-500">（{c.reason}）</span>}
            </li>
          ))}
        </ul>
      </section>

      <p>
        <Link to="/incident/$id/documents" params={{ id }} className={primary}>
          下一步：上傳文件
        </Link>
      </p>
    </div>
  );
}
