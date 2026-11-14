import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { patchIncidentTodo, sendIncidentMessage } from "../../client";
import type { IncidentContext, TodoView } from "../../client/types.gen";
import { ActionBar } from "../../components/ui/ActionBar";
import { btn, btnPri, btnSm, btnSmPri } from "../../components/ui/buttons";
import { Dialog, DialogShell } from "../../components/ui/DialogShell";
import { Pill, ProgressPill } from "../../components/ui/Tag";
import { GoogleAuthResult } from "../google/GoogleAuthResult";
import { type ChatLine, DescribeChat } from "./DescribeChat";
import { DocumentUploader } from "./DocumentUploader";
import { IncidentCard } from "./IncidentCard";
import { SendBox } from "./SendBox";
import { card, errorText, policyMeta, tripTitle, useIncident, wideMain } from "./shared";
import { progressOf, TodoCards } from "./TodoList";

const H2 = "m-0 t-section-title text-heading";

/**
 * 2-3 理賠頁（DESIGN.md 7.10）：事件問完（有事故類型）後的總覽：狀態列、狀況總結、重大注意事項、
 * 理賠待辦、送件區、問答。一個事件一頁（#214）。結案後唯讀。
 */
export function TripPage({
  id,
  ctx,
  googleUser,
}: {
  id: string;
  ctx: IncidentContext;
  googleUser: boolean;
}) {
  const { setIncident, refresh } = useIncident(id);
  const [busy, setBusy] = useState(false);
  // 問答送出中：{ 剛送出的那句話 }；只有問答才顯示 AI「輸入中」，勾選待辦不顯示
  const [asking, setAsking] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [qaOpen, setQaOpen] = useState(false); // 只在手機有意義：問答抽屜是否拉開
  // 系統已確認的待辦被取消勾選前，先問一次；需上傳但還沒有文件的待辦勾選前，也先問一次
  const [undoing, setUndoing] = useState<TodoView | null>(null);
  const [ticking, setTicking] = useState<TodoView | null>(null);

  const closed = ctx.status === "completed";
  const todos = ctx.todos ?? [];
  const { done, total } = progressOf(todos);
  const notices = ctx.major_notices ?? [];
  const clauses = ctx.clauses ?? [];

  async function toggle(todo: TodoView, checked: boolean) {
    setBusy(true);
    setError(null);
    setUndoing(null);
    setTicking(null);
    const res = await patchIncidentTodo({
      path: { incident_id: id, todo_id: todo.id },
      body: { is_done: checked },
    });
    setBusy(false);
    if (!res.data) return setError(errorText(res.error, res.response?.status));
    setIncident(res.data);
  }

  async function ask(content: string) {
    if (!content.trim() || busy) return;
    setBusy(true);
    setAsking(content);
    setError(null);
    const res = await sendIncidentMessage({
      path: { incident_id: id },
      body: { content, input_mode: "text" },
    });
    if (!res.data) {
      setAsking(null);
      setBusy(false);
      return setError(errorText(res.error, res.response?.status));
    }
    // 回應裡的事件是送出當下的快照，不能直接蓋掉快取，改成重新讀取（5 號回覆可能很慢）
    await refresh();
    setQuestion("");
    setAsking(null);
    setBusy(false);
  }

  const lines: ChatLine[] = (ctx.messages ?? []).map((m) => ({
    from: m.role === "user" ? "me" : "ai",
    text: m.content,
    citations: m.citations,
  }));
  const lastMessage = ctx.messages?.at(-1);
  if (asking && !(lastMessage?.role === "user" && lastMessage.content === asking)) {
    lines.push({ from: "me", text: asking });
  }

  return (
    <main data-page-paper className={`mx-auto flex flex-col gap-6 font-ui md:px-6 ${wideMain}`}>
      <p className="t-label m-0 text-muted">出事了：幫我處理理賠</p>

      <section
        className={`${card} flex flex-wrap items-center gap-x-6 gap-y-2`}
        aria-label="行程狀態"
      >
        <h1 className="m-0 t-section-title text-heading" data-testid="trip-title">
          {tripTitle(ctx.destination, ctx.policy.start_date, ctx.policy.end_date)}
        </h1>
        <span className="t-body text-muted">
          {policyMeta(ctx.policy.plan_name, ctx.policy.sum_insured)}
        </span>
        {total > 0 && (
          <ProgressPill>
            待辦 {done}／{total}
          </ProgressPill>
        )}
        {closed && <Pill tone="closed">已結案</Pill>}
      </section>

      <GoogleAuthResult />
      {error && (
        <p
          role="alert"
          className="m-0 rounded-btn bg-danger-soft px-4 py-2 t-caption-bold text-danger-ink"
          data-testid="error"
        >
          {error}
        </p>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[7fr_5fr] lg:items-start">
        <div className="flex flex-col gap-6 lg:col-start-1 lg:row-start-1">
          <section className="flex flex-col gap-4" aria-label="狀況總結">
            <h2 className={H2}>狀況總結</h2>
            <IncidentCard ctx={ctx} />
            <p className="m-0 t-caption text-muted">
              以上為可能適用的項目，實際以保險公司審核為準。
            </p>
          </section>

          {notices.length > 0 && (
            <section
              className={`${card} border-l-6 border-l-sun`}
              aria-label="重大注意事項"
              data-testid="major-notices-card"
            >
              <h3 className="m-0 t-subsection-title text-heading">重大注意事項</h3>
              <ol
                className="m-0 mt-2 flex list-decimal flex-col gap-1 pl-5.5"
                data-testid="major-notices"
              >
                {notices.map((n) => (
                  <li key={n}>{n}</li>
                ))}
              </ol>
            </section>
          )}

          <section className="flex flex-col gap-4" aria-label="理賠待辦">
            <h2 className={H2}>理賠待辦</h2>
            {!closed && !googleUser && todos.some((t) => t.requires_upload) && (
              <p className="m-0 rounded-btn bg-paper px-4 py-2 t-caption text-muted">
                你不是用 Google 登入，文件無法存到 Google Drive，之後也不能用 Gmail 寄出送件信。
              </p>
            )}
            {!closed && todos.some((t) => t.requires_upload) && (
              <DocumentUploader
                id={id}
                ctx={ctx}
                googleUser={googleUser}
                next={`/incident/${id}`}
                onError={setError}
              />
            )}
            {todos.length === 0 ? (
              <p className="m-0 t-body text-muted" data-testid="no-todos">
                {clauses.some((c) => c.conclusion === "insufficient")
                  ? "目前沒有待辦：有項目還在待確認事項，需要補充資訊後才會產生待辦。"
                  : "目前沒有「可能適用」的保障項目，所以沒有待辦。"}
              </p>
            ) : (
              <>
                {!closed && total > 0 && done === total && (
                  <p
                    className="m-0 rounded-tile bg-leaf-soft px-5 py-4 t-label text-heading"
                    data-testid="all-done"
                  >
                    所有待辦都完成了，可以送件。
                  </p>
                )}
                <TodoCards
                  ctx={ctx}
                  disabled={busy || closed}
                  onToggle={(todo, checked) => {
                    if (todo.done_by === "agent" && !checked) return setUndoing(todo);
                    const hasFile = (ctx.documents ?? []).some((d) => d.todo_id === todo.id);
                    if (checked && todo.requires_upload && !hasFile) return setTicking(todo);
                    void toggle(todo, checked);
                  }}
                />
              </>
            )}
          </section>

          {todos.length > 0 && (
            <SendBox
              id={id}
              todos={todos}
              closed={closed}
              hasFiles={(ctx.documents ?? []).some((d) => d.storage_path)}
            />
          )}
        </div>

        {/* 手機：問答預設收起，右緣的圓鈕點開，從底部拉起（設計稿 v3.7）；桌機是右欄 */}
        {qaOpen && (
          <button
            type="button"
            aria-label="收起問答"
            tabIndex={-1}
            onClick={() => setQaOpen(false)}
            className="fixed inset-0 z-30 border-0 bg-scrim p-0 lg:hidden"
          />
        )}
        {!qaOpen && (
          <button
            type="button"
            aria-expanded={false}
            aria-controls="trip-qa"
            onClick={() => setQaOpen(true)}
            data-testid="qa-open"
            className="fixed right-[-44px] bottom-28 z-30 flex size-[92px] items-center rounded-full border-0 bg-brand pl-3.5 text-left t-label-lg text-white shadow-dialog lg:hidden"
          >
            問答
          </button>
        )}
        <section
          id="trip-qa"
          className={`flex flex-col gap-4 lg:sticky lg:top-6 lg:col-start-2 lg:row-start-1 max-lg:fixed max-lg:inset-x-0 max-lg:bottom-0 max-lg:z-40 max-lg:h-[75dvh] max-lg:overflow-y-auto max-lg:rounded-t-[20px] max-lg:bg-paper max-lg:px-4 max-lg:pt-2 max-lg:pb-5 max-lg:shadow-dialog ${
            qaOpen ? "" : "max-lg:hidden"
          }`}
          aria-label="問答"
        >
          <span
            aria-hidden="true"
            className="mx-auto mt-1 block h-[5px] w-11 rounded-sm bg-line lg:hidden"
          />
          <div className="flex items-center gap-3">
            <h2 className={H2}>問答</h2>
            <button
              type="button"
              onClick={() => setQaOpen(false)}
              data-testid="qa-close"
              className={`${btnSm} ml-auto lg:hidden`}
            >
              收起
            </button>
          </div>
          {closed ? (
            <p className={`${card} m-0 t-body text-muted`} data-testid="closed-banner">
              這筆理賠已結案，只能查看。
            </p>
          ) : (
            <>
              <DescribeChat
                lines={lines}
                quickReplies={[]}
                placeholder="關於這次理賠的任何問題"
                value={question}
                onChange={setQuestion}
                busy={busy}
                typing={asking !== null}
                onSend={(content) => void ask(content)}
                maxLength={300}
                minHeight={180}
                tall
                fill
                logFooter={
                  ctx.policy.policy_id ? (
                    <Link
                      to="/incident/new/$policyId"
                      params={{ policyId: ctx.policy.policy_id }}
                      className={btnSmPri}
                    >
                      ＋ 有新狀況
                    </Link>
                  ) : undefined
                }
              />
              <p className="m-0 t-caption text-muted">
                回答由 AI 依條款整理，實際以保險公司審核為準。
              </p>
            </>
          )}
        </section>
      </div>

      <ActionBar>
        <ActionBar.Push>
          <Link to="/" className={btn}>
            完成
          </Link>
        </ActionBar.Push>
      </ActionBar>

      <DialogShell
        open={ticking !== null}
        onOpenChange={(open) => !open && setTicking(null)}
        title="尚未確認文件，確定要打勾嗎？"
        description={
          <p>
            這項待辦的文件還沒有上傳。打勾後會標記「未附文件」，送件的信裡會寫「另行提供」，只附上已上傳的文件。
          </p>
        }
        testId="tick-dialog"
        actions={
          <>
            <Dialog.Close className={btn}>回待辦清單</Dialog.Close>
            <button
              type="button"
              className={btnPri}
              data-testid="tick-confirm"
              onClick={() => ticking && void toggle(ticking, true)}
            >
              我要打勾
            </button>
          </>
        }
      />
      <DialogShell
        open={undoing !== null}
        onOpenChange={(open) => !open && setUndoing(null)}
        title="取消這個待辦？"
        description={<p>這項是系統看過你的文件後確認的，確定要取消？</p>}
        testId="undo-dialog"
        actions={
          <>
            <Dialog.Close className={btn}>保留</Dialog.Close>
            <button
              type="button"
              className={btn}
              onClick={() => undoing && void toggle(undoing, false)}
            >
              確定取消
            </button>
          </>
        }
      />
    </main>
  );
}
