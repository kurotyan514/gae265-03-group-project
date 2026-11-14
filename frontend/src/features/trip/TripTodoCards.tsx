import type { DocumentView, TodoView, TripOut } from "../../client/types.gen";
import { ProgressPill } from "../../components/ui/Tag";
import { dateOf } from "../incident/IncidentCard";
import { card } from "../incident/shared";
import { isNa, PHASES, TodoRow } from "../incident/TodoList";

/** 不符保障的事故裡，有範本的（文件類）待辦：反灰、不計入完成度與送件檢查（ADR-0029）。 */
const greyed = (todo: TodoView, covered: boolean) => !covered && todo.template_id != null;

const sorted = (list: TodoView[]) =>
  [...list].sort(
    (a, b) => Number(isNa(a)) - Number(isNa(b)) || (a.sort_order ?? 0) - (b.sort_order ?? 0),
  );

/** 行程的待辦完成度：整個行程合計，不含不適用與反灰的。 */
export function tripProgress(trip: TripOut) {
  const todos = [
    ...trip.shared_todos,
    ...trip.incidents.flatMap((i) => i.todos.filter((t) => !greyed(t, i.covered))),
  ].filter((t) => !isNa(t));
  return { done: todos.filter((t) => t.is_done).length, total: todos.length };
}

/** 送件前還差什麼：還缺的文件份數（需上傳、沒勾）與其他沒勾的待辦；不含不適用與反灰的。 */
export function tripPending(trip: TripOut) {
  const todos = [
    ...trip.shared_todos,
    ...trip.incidents.flatMap((i) => i.todos.filter((t) => !greyed(t, i.covered))),
  ].filter((t) => !isNa(t) && !t.is_done);
  const missingUploads = todos.filter((t) => t.requires_upload).length;
  return { missingUploads, pending: todos.length - missingUploads };
}

/**
 * 待辦清單（規格 7.3.3）：「事故當下」與「回國後整理」兩張卡，卡內依事故分組（小標題＝事故類型＋日期），
 * 最後一組「整個行程」放共同文件（機票、理賠申請書、存摺與護照影本、受益人身分證明，ADR-0029）。
 */
export function TripTodoCards({
  trip,
  disabled,
  onToggle,
}: {
  trip: TripOut;
  disabled: boolean;
  onToggle: (todo: TodoView, checked: boolean) => void;
}) {
  const documents: DocumentView[] = [
    ...trip.shared_documents,
    ...trip.incidents.flatMap((i) => i.documents),
  ];
  return (
    <div className="flex flex-col gap-6" data-testid="todos">
      {PHASES.map(({ phase, title }) => {
        const groups = [
          ...trip.incidents.map((i) => ({
            key: i.id,
            title: `${i.incident_type_name ?? "事故"}${dateOf(i) ? ` · ${dateOf(i)}` : ""}`,
            covered: i.covered,
            items: sorted(i.todos.filter((t) => t.phase === phase)),
          })),
          {
            key: "trip",
            title: "整個行程",
            covered: true,
            items: sorted(trip.shared_todos.filter((t) => t.phase === phase)),
          },
        ].filter((g) => g.items.length > 0);
        if (groups.length === 0) return null;
        const counted = groups.flatMap((g) =>
          g.items.filter((t) => !isNa(t) && !greyed(t, g.covered)),
        );
        return (
          <section key={phase} className={card} aria-label={title}>
            <div className="mb-1.5 flex flex-wrap items-center gap-3">
              <h3 className="m-0 t-subsection-title text-heading">{title}</h3>
              <ProgressPill>
                {counted.filter((t) => t.is_done).length}／{counted.length}
              </ProgressPill>
            </div>
            {groups.map((g) => (
              <div key={g.key} data-testid={g.key === "trip" ? "todo-group-trip" : "todo-group"}>
                <h4 className="m-0 mt-4.5 flex items-center gap-2 border-b border-line pt-1.5 pb-2.5 t-label text-heading before:h-4 before:w-1 before:rounded-sm before:bg-leaf">
                  {g.title}
                </h4>
                <ul className="m-0 list-none p-0">
                  {g.items.map((t) => (
                    <TodoRow
                      key={t.id}
                      todo={t}
                      disabled={disabled}
                      muted={greyed(t, g.covered)}
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
