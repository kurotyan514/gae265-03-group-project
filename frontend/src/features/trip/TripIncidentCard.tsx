import type { TripIncidentOut } from "../../client/types.gen";
import { btnSm } from "../../components/ui/buttons";
import { dateOf, IncidentCardBody } from "../incident/IncidentCard";
import { card } from "../incident/shared";

const TAG = "rounded-xl px-2.5 py-0.5 text-[13px] leading-5 font-bold";

/**
 * 行程頁的事故卡（規格 2-3a）：標題列＝事故類型與發生日期、標籤；沒選中的事故右側有「問答」與「▸」。
 * 選中的事故一定展開（右欄問答顯示它的對話）；其他預設收起，按「▸」展開。
 */
export function TripIncidentCard({
  incident,
  selected,
  expanded,
  locked,
  onAsk,
  onToggle,
}: {
  incident: TripIncidentOut;
  selected: boolean;
  expanded: boolean;
  /** 行程結案後沒有問答，只剩展開收起。 */
  locked: boolean;
  onAsk: () => void;
  onToggle: () => void;
}) {
  const date = dateOf(incident);
  const name = `${incident.incident_type_name ?? "事故"}${date ? ` · ${date}` : ""}`;
  const unsure = incident.clauses.filter((c) => c.conclusion === "insufficient").length;
  const open = selected || expanded;
  const bodyId = `incident-${incident.id}`;
  return (
    <article
      className={`${card} flex flex-col gap-3.5`}
      aria-label={`事故 ${name}`}
      data-testid="trip-incident"
      data-incident-id={incident.id}
      data-selected={selected || undefined}
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <h3 className="m-0 t-subsection-title text-heading" data-testid="incident-type">
          {name}
        </h3>
        {unsure > 0 && (
          <span data-testid="unsure-count" className={`${TAG} bg-warn-soft text-warn-ink`}>
            待確認 {unsure}
          </span>
        )}
        {!incident.covered && (
          <span data-testid="not-covered" className={`${TAG} bg-paper text-muted`}>
            不符保障
          </span>
        )}
        {!selected && (
          <span className="ml-auto flex items-center gap-2">
            {!locked && (
              <button type="button" className={btnSm} onClick={onAsk} data-testid="incident-ask">
                問答
              </button>
            )}
            <button
              type="button"
              aria-expanded={open}
              aria-controls={bodyId}
              aria-label={`${open ? "收起" : "展開"}${name}`}
              onClick={onToggle}
              data-testid="incident-toggle"
              className="grid size-9 place-items-center rounded-tag border border-line bg-white text-leaf-text hover:border-brand"
            >
              {open ? "▾" : "▸"}
            </button>
          </span>
        )}
      </div>
      {!incident.covered && (
        <p className="m-0 t-caption text-muted">
          這個事故依條款不在保障範圍，文件類待辦不需要準備、不計入送件檢查。
        </p>
      )}
      <IncidentCardBody ctx={incident} id={bodyId} hidden={!open} />
    </article>
  );
}
