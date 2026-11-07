import { Link } from "@tanstack/react-router";
import type { RecentComparisonOut } from "../../client/types.gen";
import { ChevronIcon, PlaneIcon } from "../../components/icons";
import { wan } from "../../lib/format";

/**
 * 比較紀錄的一列（首頁「最近的比較」；全部比較頁共用）。整列是連結：
 * 已推薦到 1-3，還在填寫（沒有推薦）到 1-2。
 */
export function ComparisonRow({ comparison: c }: { comparison: RecentComparisonOut }) {
  const rec = c.recommended;
  const className =
    "group flex items-center gap-3 border-b border-line py-4 last:border-b-0 md:gap-6 md:py-[22px] md:pr-2";
  const content = (
    <>
      <span className="grid size-10 flex-none place-items-center rounded-full bg-leaf-soft text-leaf md:size-[52px]">
        <PlaneIcon className="size-[22px] md:size-7" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-bold leading-[22px] text-ink md:text-lg md:leading-7">
          {c.destination} · {c.depart_date.replaceAll("-", "/")} · {c.days} 天
        </span>
        <span className="mt-1 block text-sm leading-[22px] text-ink md:mt-1.5 md:text-base md:leading-[26px]">
          {rec ? `推薦 ${rec.company} ${rec.name} · ${wan(rec.sum_insured)}` : "填寫中"}
        </span>
      </span>
      <span className="grid size-[26px] flex-none place-items-center rounded-full bg-leaf-soft text-leaf transition-colors group-hover:bg-leaf group-hover:text-white md:size-[30px]">
        <ChevronIcon className="size-4" />
      </span>
    </>
  );
  return (
    <Link
      to={rec ? "/compare/$id/result" : "/compare/$id/concerns"}
      params={{ id: c.id }}
      className={className}
    >
      {content}
    </Link>
  );
}
