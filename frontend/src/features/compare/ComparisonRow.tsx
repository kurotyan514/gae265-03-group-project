import { Link } from "@tanstack/react-router";
import type { RecentComparisonOut } from "../../client/types.gen";
import { ChevronIcon, PlaneIcon } from "../../components/icons";

const wan = (n: number) => `${(n / 10_000).toLocaleString("zh-TW")} 萬`;

/**
 * 比較紀錄的一列（首頁「最近的比較」；全部比較頁共用）。整列是連結：
 * 已推薦到 1-3，還在填寫（沒有推薦）到 1-2。
 */
export function ComparisonRow({ comparison: c }: { comparison: RecentComparisonOut }) {
  const rec = c.recommended;
  const className =
    "group flex items-center gap-3 border-b border-line py-4 pr-2 last:border-b-0 sm:gap-6 sm:py-[22px]";
  const content = (
    <>
      <span className="grid size-10 flex-none place-items-center rounded-full bg-leaf-soft text-leaf sm:size-[52px]">
        <PlaneIcon className="size-[22px] sm:size-7" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-bold leading-[22px] text-ink sm:text-lg sm:leading-7">
          {c.destination} · {c.depart_date.replaceAll("-", "/")} · {c.days} 天
        </span>
        <span className="mt-1 block text-sm leading-[22px] text-ink sm:mt-1.5 sm:text-base sm:leading-[26px]">
          {rec ? `推薦 ${rec.company} ${rec.name} · ${wan(rec.sum_insured)}` : "填寫中"}
        </span>
      </span>
      <span className="grid size-[26px] flex-none place-items-center rounded-full bg-leaf-soft text-leaf transition-colors group-hover:bg-leaf group-hover:text-white sm:size-[30px]">
        <ChevronIcon className="size-4" />
      </span>
    </>
  );
  return rec ? (
    <Link to="/compare/$id/result" params={{ id: c.id }} className={className}>
      {content}
    </Link>
  ) : (
    <Link to="/compare/$id/concerns" params={{ id: c.id }} className={className}>
      {content}
    </Link>
  );
}
