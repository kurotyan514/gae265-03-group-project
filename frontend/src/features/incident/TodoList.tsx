import { Link } from "@tanstack/react-router";
import { useState } from "react";
import type { DocumentView, IncidentContext, TodoView } from "../../client/types.gen";
import { btnSm } from "../../components/ui/buttons";
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

/** 一項待辦（DESIGN.md 6.25）：勾選框、名稱與標籤、已上傳的檔案、等待說明、注意事項、上傳。 */
function TodoRow({
  todo: t,
  documents,
  incidentId,
  disabled,
  onToggle,
}: {
  todo: TodoView;
  documents: DocumentView[];
  incidentId: string;
  /** 結案、處理中時停用。 */
  disabled: boolean;
  onToggle: (todo: TodoView, checked: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const na = isNa(t);
  const notes = t.notes ?? [];
  return (
    <li
      className={`grid grid-cols-[28px_1fr] gap-x-3.5 gap-y-1.5 border-b border-line py-4 last:border-b-0 ${
        na ? "opacity-75" : ""
      }`}
    >
      <input
        type="checkbox"
        checked={t.is_done ?? false}
        // 需上傳的待辦也可以自己勾（規格 v3.4）：沒有文件時會標「未附文件」，勾之前先確認
        disabled={disabled || na}
        onChange={(e) => onToggle(t, e.target.checked)}
        aria-label={t.title}
        className="mt-1 size-[22px] cursor-pointer accent-brand disabled:cursor-not-allowed"
      />
      <div className="flex min-w-0 flex-col gap-2">
        <p
          className={`m-0 t-label-lg ${
            na ? "font-normal text-muted line-through" : t.is_done ? "text-muted" : "text-ink"
          }`}
        >
          {t.title}
          {!t.template_id && t.scope !== "policy" && <TodoTag tone="new">新增</TodoTag>}
          {na && <TodoTag>不適用</TodoTag>}
          {t.without_document && <TodoTag tone="missing">未附文件</TodoTag>}
          {t.done_by === "agent" && <TodoTag>系統確認</TodoTag>}
        </p>
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
        {t.wait_note && <p className="m-0 t-caption text-muted">⏱ {t.wait_note}</p>}
        {t.requires_upload && !na && !disabled && (
          <Link
            to="/incident/$id/documents"
            params={{ id: incidentId }}
            className={`${btnSm} self-start`}
          >
            上傳
          </Link>
        )}
        {(t.note || notes.length > 0) && (
          <div className="t-caption text-muted">
            {t.note && <span>注意：{t.note}</span>}
            {notes.length > 0 && (
              <>
                {" "}
                <button
                  type="button"
                  aria-expanded={open}
                  onClick={() => setOpen(!open)}
                  className="border-0 bg-transparent p-0 t-caption-bold text-leaf-text hover:underline"
                >
                  {open ? "收合" : "展開"}
                </button>
                {open && (
                  <ul className="m-0 mt-1 list-disc pl-5.5">
                    {notes.map((n) => (
                      <li key={n}>{n}</li>
                    ))}
                  </ul>
                )}
              </>
            )}
          </div>
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
  incidentId,
  disabled,
  onToggle,
}: {
  ctx: IncidentContext;
  incidentId: string;
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
                      incidentId={incidentId}
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
