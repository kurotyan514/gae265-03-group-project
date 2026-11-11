import { Link } from "@tanstack/react-router";
import type { IncidentSummaryOut } from "../../client/types.gen";
import { ChevronIcon, ShieldIcon } from "../../components/icons";
import { taipeiDate } from "../../lib/format";

/** 事件的狀態標籤（只有 open／completed 兩種）。 */
const STATUS_LABEL: Record<string, string> = { open: "進行中", completed: "已完成" };

/**
 * 首頁「我的理賠」的一列。整列是連結，一律進事件的第一步（說明狀況與待辦）。
 * 標題為主；下一行是「事故類型 · 最後操作 日期」，類型還沒判斷出來就只顯示日期。清單也依最後操作時間排序。
 */
export function IncidentRow({ incident: i }: { incident: IncidentSummaryOut }) {
  const done = i.status === "completed";
  return (
    <Link
      to="/incident/$id"
      params={{ id: i.id }}
      className="group flex items-center gap-3 border-b border-line py-4 last:border-b-0 md:gap-6 md:py-[22px] md:pr-2"
    >
      <span className="grid size-10 flex-none place-items-center rounded-full bg-leaf-soft text-leaf md:size-[52px]">
        <ShieldIcon className="size-[22px] md:size-7" />
      </span>
      <span className="min-w-0 flex-1">
        <span
          data-testid="incident-row-title"
          className="block truncate text-sm font-bold leading-[22px] text-ink md:text-lg md:leading-7"
        >
          {i.title}
        </span>
        <span className="mt-1 block truncate text-sm leading-[22px] text-ink md:mt-1.5 md:text-base md:leading-[26px]">
          {[i.incident_type_name, `最後操作 ${taipeiDate(i.last_activity_at)}`]
            .filter(Boolean)
            .join(" · ")}
        </span>
      </span>
      <span
        data-testid="incident-row-status"
        className={`flex-none rounded-full px-2.5 py-0.5 text-xs font-bold leading-[18px] md:text-sm ${
          done ? "bg-line/60 text-muted" : "bg-leaf-soft text-leaf"
        }`}
      >
        {STATUS_LABEL[i.status] ?? i.status}
      </span>
      <span className="grid size-[26px] flex-none place-items-center rounded-full bg-leaf-soft text-leaf transition-colors group-hover:bg-leaf group-hover:text-white md:size-[30px]">
        <ChevronIcon className="size-4" />
      </span>
    </Link>
  );
}
