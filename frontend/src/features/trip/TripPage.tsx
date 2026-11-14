import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { patchTripTodo, sendIncidentMessage } from "../../client";
import type { TodoView, TripOut } from "../../client/types.gen";
import { ActionBar } from "../../components/ui/ActionBar";
import { btn, btnPri, btnSm } from "../../components/ui/buttons";
import { Dialog, DialogShell } from "../../components/ui/DialogShell";
import { Pill, ProgressPill } from "../../components/ui/Tag";
import { GoogleAuthResult } from "../google/GoogleAuthResult";
import { type ChatLine, DescribeChat } from "../incident/DescribeChat";
import { card, errorText, policyMeta, tripTitle, useIncident, wideMain } from "../incident/shared";
import { TripIncidentCard } from "./TripIncidentCard";
import { TripSendBox } from "./TripSendBox";
import { TripTodoCards, tripProgress } from "./TripTodoCards";
import { TripUploader } from "./TripUploader";
import { useTrip } from "./useTrip";

const H2 = "m-0 t-section-title text-heading";

/**
 * 行程頁（規格 2-3，ADR-0029）：一張保單的所有事故收在一頁——事故卡、重大注意事項、待辦（依事故分組加
 * 「整個行程」的共同文件）、上傳框（整個行程一個）、問答（右欄，依選中的事故分開）。送件在後續版本接上。
 * 行程結案（送件或結案）後唯讀。
 */
export function TripPage({
  policyId,
  trip,
  googleUser,
}: {
  policyId: string;
  trip: TripOut;
  googleUser: boolean;
}) {
  const { setTrip, refresh } = useTrip(policyId);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // 選中的事故一定展開；其他的按「▸」展開，展開過的維持展開（規格 7.3.1）
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [asking, setAsking] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [qaOpen, setQaOpen] = useState(false); // 只在手機有意義：問答面板是否拉開
  const [undoing, setUndoing] = useState<TodoView | null>(null);
  const [ticking, setTicking] = useState<TodoView | null>(null);

  const locked = trip.locked;
  // 預設選中發生日期最早的事故（事故已依發生時間排序）
  const selected = trip.incidents.find((i) => i.id === selectedId) ?? trip.incidents[0];
  const { data: ctx, refresh: refreshIncident } = useIncident(selected?.id ?? "");
  const { done, total } = tripProgress(trip);
  const hasUpload = [...trip.shared_todos, ...trip.incidents.flatMap((i) => i.todos)].some(
    (t) => t.requires_upload,
  );

  async function toggle(todo: TodoView, checked: boolean) {
    setBusy(true);
    setError(null);
    setUndoing(null);
    setTicking(null);
    const res = await patchTripTodo({
      path: { policy_id: policyId, todo_id: todo.id },
      body: { is_done: checked },
    });
    setBusy(false);
    if (!res.data) return setError(errorText(res.error, res.response?.status));
    setTrip(res.data);
  }

  function onToggle(todo: TodoView, checked: boolean) {
    if (todo.done_by === "agent" && !checked) return setUndoing(todo);
    const hasFile = [...trip.shared_documents, ...trip.incidents.flatMap((i) => i.documents)].some(
      (d) => d.todo_id === todo.id,
    );
    if (checked && todo.requires_upload && !hasFile) return setTicking(todo);
    void toggle(todo, checked);
  }

  async function ask(content: string) {
    if (!selected || !content.trim() || busy) return;
    setBusy(true);
    setAsking(content);
    setError(null);
    const res = await sendIncidentMessage({
      path: { incident_id: selected.id },
      body: { content, input_mode: "text" },
    });
    if (!res.data) {
      setAsking(null);
      setBusy(false);
      return setError(errorText(res.error, res.response?.status));
    }
    // 回應是送出當下的快照（5 號回覆可能很慢），改成重新讀取；問答可能改了待辦，行程也一起讀
    await Promise.all([refresh(), refreshIncident()]);
    setQuestion("");
    setAsking(null);
    setBusy(false);
  }

  const lines: ChatLine[] = (ctx?.messages ?? []).map((m) => ({
    from: m.role === "user" ? "me" : "ai",
    text: m.content,
    citations: m.citations,
  }));
  const lastMessage = ctx?.messages?.at(-1);
  if (asking && !(lastMessage?.role === "user" && lastMessage.content === asking)) {
    lines.push({ from: "me", text: asking });
  }

  function select(id: string, openPanel: boolean) {
    setSelectedId(id);
    setExpanded((prev) => new Set(prev).add(id));
    if (openPanel) setQaOpen(true);
  }

  return (
    <main data-page-paper className={`mx-auto flex flex-col gap-6 font-ui md:px-6 ${wideMain}`}>
      <p className="t-label m-0 text-muted">出事了：幫我處理理賠</p>

      <section
        className={`${card} flex flex-wrap items-center gap-x-6 gap-y-2`}
        aria-label="行程狀態"
      >
        <h1 className="m-0 t-section-title text-heading" data-testid="trip-title">
          {tripTitle(trip.destination, trip.policy.start_date, trip.policy.end_date)}
        </h1>
        <span className="t-body text-muted">
          {policyMeta(trip.policy.plan_name, trip.policy.sum_insured)}
        </span>
        {total > 0 && (
          <ProgressPill>
            待辦 {done}／{total}
          </ProgressPill>
        )}
        {locked && <Pill tone="closed">已結案</Pill>}
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
            {trip.incidents.map((incident) => (
              <TripIncidentCard
                key={incident.id}
                incident={incident}
                selected={incident.id === selected?.id}
                expanded={expanded.has(incident.id)}
                locked={locked}
                onAsk={() => select(incident.id, true)}
                onToggle={() =>
                  setExpanded((prev) => {
                    const next = new Set(prev);
                    if (!next.delete(incident.id)) next.add(incident.id);
                    return next;
                  })
                }
              />
            ))}
            <p className="m-0 t-caption text-muted">
              以上為可能適用的項目，實際以保險公司審核為準。
            </p>
          </section>

          {trip.major_notices.length > 0 && (
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
                {trip.major_notices.map((n) => (
                  <li key={n}>{n}</li>
                ))}
              </ol>
            </section>
          )}

          <section className="flex flex-col gap-4" aria-label="理賠待辦">
            <h2 className={H2}>理賠待辦</h2>
            {total === 0 ? (
              <p className="m-0 t-body text-muted" data-testid="no-todos">
                目前沒有待辦：沒有「可能適用」的保障項目，或還有項目在待確認事項，需要補充資訊後才會產生待辦。
              </p>
            ) : (
              <>
                {!locked && !googleUser && hasUpload && (
                  <p className="m-0 rounded-btn bg-paper px-4 py-2 t-caption text-muted">
                    你不是用 Google 登入，文件無法存到 Google Drive，之後也不能用 Gmail 寄出送件信。
                  </p>
                )}
                {!locked && hasUpload && (
                  <TripUploader
                    policyId={policyId}
                    trip={trip}
                    googleUser={googleUser}
                    onError={setError}
                  />
                )}
                {!locked && done === total && (
                  <p
                    className="m-0 rounded-tile bg-leaf-soft px-5 py-4 t-label text-heading"
                    data-testid="all-done"
                  >
                    所有待辦都完成了，可以送件。
                  </p>
                )}
                <TripTodoCards trip={trip} disabled={busy || locked} onToggle={onToggle} />
              </>
            )}
          </section>

          <TripSendBox policyId={policyId} trip={trip} />
        </div>

        {/* 手機：按事故卡的「問答」，該事故的問答面板從下方滑出；桌機是固定的右欄 */}
        {qaOpen && (
          <button
            type="button"
            aria-label="收起問答"
            tabIndex={-1}
            onClick={() => setQaOpen(false)}
            className="fixed inset-0 z-30 border-0 bg-scrim p-0 lg:hidden"
          />
        )}
        {!locked && selected && (
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
              <h2 className={H2} data-testid="qa-title">
                問答 · {selected.incident_type_name ?? "事故"}
              </h2>
              <button
                type="button"
                onClick={() => setQaOpen(false)}
                data-testid="qa-close"
                className={`${btnSm} ml-auto lg:hidden`}
              >
                收起
              </button>
            </div>
            <DescribeChat
              lines={lines}
              quickReplies={[]}
              placeholder="關於這個事故的任何問題"
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
                <Link
                  to="/incident/new/$policyId"
                  params={{ policyId }}
                  className={btnSm}
                  data-testid="new-incident"
                >
                  ＋ 有新狀況
                </Link>
              }
            />
            <p className="m-0 t-caption text-muted">
              回答由 AI 依條款整理，實際以保險公司審核為準。
            </p>
          </section>
        )}
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
