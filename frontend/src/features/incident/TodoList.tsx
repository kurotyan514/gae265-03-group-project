import { useState } from "react";
import type { DocumentView, IncidentContext, TodoView } from "../../client/types.gen";
import { PlaceholderButton } from "../../components/ui/PlaceholderButton";
import { ProgressPill, TodoTag } from "../../components/ui/Tag";
import { dateOf } from "./IncidentCard";
import { card } from "./shared";

const isNa = (t: TodoView) => t.applicable === false;

/** 「待辦 N／M」：不適用的不算。 */
export function progressOf(todos: TodoView[]) {
  const active = todos.filter((t) => !isNa(t));
  return { done: active.filter((t) => t.is_done).length, total: active.length };
}

/** 狀態晶片（設計稿 v3.7）：已附檔案數、等待說明、待上傳；其餘不顯示。 */
function statusOf(t: TodoView, fileCount: number): { text: string; className: string } | null {
  if (isNa(t)) return null;
  if (fileCount > 0) return { text: `${fileCount} 份檔案`, className: "bg-leaf-soft text-brand" };
  if (t.wait_note) return { text: `⏱ ${t.wait_note}`, className: "bg-paper text-muted" };
  if (t.requires_upload && !t.is_done) {
    return { text: "待上傳", className: "border border-line bg-white text-muted" };
  }
  return null;
}

/**
 * 一項待辦（設計稿 v3.7）：一行＝勾選框、名稱與標籤、右側狀態晶片、展開箭頭；
 * 展開後看已附檔案、等待與上傳說明、注意事項。手機版晶片排到名稱下一行。
 */
function TodoRow({
  todo: t,
  documents,
  disabled,
  onToggle,
}: {
  todo: TodoView;
  documents: DocumentView[];
  /** 結案、處理中時停用。 */
  disabled: boolean;
  onToggle: (todo: TodoView, checked: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const na = isNa(t);
  const notes = t.notes ?? [];
  const status = statusOf(t, documents.length);
  const needUpload = t.requires_upload && !t.is_done && !na && documents.length === 0;
  const panelId = `todo-${t.id}`;
  return (
    <li className={`border-b border-line last:border-b-0 ${na ? "opacity-75" : ""}`}>
      <div className="flex items-start gap-2.5 py-3.5 md:gap-3">
        <input
          type="checkbox"
          checked={t.is_done ?? false}
          // 需上傳的待辦也可以自己勾（規格 v3.4）：沒有文件時會標「未附文件」，勾之前先確認
          disabled={disabled || na}
          onChange={(e) => onToggle(t, e.target.checked)}
          aria-label={t.title}
          className="mt-0.5 size-[22px] shrink-0 cursor-pointer accent-brand disabled:cursor-not-allowed"
        />
        <button
          type="button"
          aria-expanded={open}
          aria-controls={panelId}
          onClick={() => setOpen(!open)}
          data-testid="todo-toggle"
          className="grid min-w-0 flex-1 grid-cols-[minmax(0,1fr)_18px] items-center gap-x-3 gap-y-1.5 border-0 bg-transparent p-0 text-left focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-leaf md:grid-cols-[minmax(0,1fr)_auto_18px]"
        >
          <span
            className={`t-label-lg ${
              na ? "font-normal text-muted line-through" : t.is_done ? "text-muted" : "text-ink"
            }`}
          >
            {t.title}
            {/* 狀況更新後才加入或又適用的待辦，勾選後消失（規格 4.5 R5） */}
            {!na && (t.is_new || (!t.template_id && t.scope !== "policy")) && (
              <TodoTag tone="new">新增</TodoTag>
            )}
            {na && <TodoTag>不適用</TodoTag>}
            {t.without_document && <TodoTag tone="missing">未附文件</TodoTag>}
            {t.done_by === "agent" && <TodoTag>AI 已打勾</TodoTag>}
          </span>
          {status && (
            <span
              data-testid="todo-status"
              className={`row-start-2 justify-self-start rounded-xl px-2.5 py-0.5 text-[13px] leading-5 font-bold whitespace-nowrap md:row-start-auto md:justify-self-end ${status.className}`}
            >
              {status.text}
            </span>
          )}
          <span
            aria-hidden="true"
            className={`col-start-2 row-start-1 flex size-[18px] items-center justify-center text-leaf-text transition-transform md:col-start-3 ${
              open ? "rotate-180" : ""
            }`}
          >
            <svg
              viewBox="0 0 24 24"
              className="size-[18px]"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.4"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="m6 9 6 6 6-6" />
            </svg>
          </span>
        </button>
      </div>
      {/* 收合時仍在畫面外保留內容（測試與讀屏都找得到），所以用 hidden 而不是不渲染 */}
      <div
        id={panelId}
        hidden={!open}
        className="flex flex-col gap-2 pb-4 pl-[34px] t-caption text-muted md:pl-10"
      >
        {na && (
          <p className="m-0" data-testid="todo-not-needed">
            依最新狀況已不需要
          </p>
        )}
        {documents.length > 0 && (
          <ul className="m-0 flex list-none flex-col gap-1 p-0" data-testid="todo-files">
            {documents.map((d) => (
              <li key={d.id} className="flex flex-wrap items-center gap-2.5 t-caption text-brand">
                <span className="[overflow-wrap:anywhere] font-bold">📎 {d.file_name}</span>
                <PlaceholderButton kind="danger-link">刪除</PlaceholderButton>
              </li>
            ))}
          </ul>
        )}
        {t.wait_note && <p className="m-0">⏱ {t.wait_note}</p>}
        {needUpload && !disabled && <p className="m-0">尚未上傳（用上方「上傳理賠文件」）</p>}
        {t.note && <p className="m-0">注意：{t.note}</p>}
        {notes.length > 0 && (
          <ul className="m-0 list-disc pl-5.5">
            {notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        )}
      </div>
    </li>
  );
}

const PHASES = [
  { phase: "on_site", title: "事故當下" },
  { phase: "after_return", title: "回國後整理" },
] as const;

/**
 * 待辦清單：分成「事故當下」與「回國後整理」兩張卡，每張卡裡先列這個事故的待辦，
 * 再列「整個行程」共用的待辦（理賠申請書）。不適用的排在同組最後。
 */
export function TodoCards({
  ctx,
  disabled,
  onToggle,
}: {
  ctx: IncidentContext;
  disabled: boolean;
  onToggle: (todo: TodoView, checked: boolean) => void;
}) {
  const todos = ctx.todos ?? [];
  const documents = ctx.documents ?? [];
  const date = dateOf(ctx);
  const incidentTitle = `${ctx.incident_type_name ?? "這次事故"}${date ? ` · ${date}` : ""}`;
  const sorted = (list: TodoView[]) =>
    [...list].sort(
      (a, b) => Number(isNa(a)) - Number(isNa(b)) || (a.sort_order ?? 0) - (b.sort_order ?? 0),
    );

  return (
    <div className="flex flex-col gap-6" data-testid="todos">
      {PHASES.map(({ phase, title }) => {
        const inPhase = todos.filter((t) => t.phase === phase);
        if (inPhase.length === 0) return null;
        const groups = [
          { title: incidentTitle, items: sorted(inPhase.filter((t) => t.scope !== "policy")) },
          { title: "整個行程", items: sorted(inPhase.filter((t) => t.scope === "policy")) },
        ].filter((g) => g.items.length > 0);
        const { done, total } = progressOf(inPhase);
        return (
          <section key={phase} className={card} aria-label={title}>
            <div className="mb-1.5 flex flex-wrap items-center gap-3">
              <h3 className="m-0 t-subsection-title text-heading">{title}</h3>
              <ProgressPill>
                {done}／{total}
              </ProgressPill>
            </div>
            {groups.map((g) => (
              <div key={g.title}>
                <h4 className="m-0 mt-4.5 flex items-center gap-2 border-b border-line pt-1.5 pb-2.5 t-label text-heading before:h-4 before:w-1 before:rounded-sm before:bg-sun">
                  {g.title}
                </h4>
                <ul className="m-0 list-none p-0">
                  {g.items.map((t) => (
                    <TodoRow
                      key={t.id}
                      todo={t}
                      disabled={disabled}
                      documents={documents.filter((d) => d.todo_id === t.id)}
                      onToggle={onToggle}
                    />
                  ))}
                </ul>
              </div>
            ))}
          </section>
        );
      })}
    </div>
  );
}
