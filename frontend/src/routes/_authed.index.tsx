import { useQuery } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import type { ReactNode } from "react";
import {
  listIncidentsOptions,
  listRecentComparisonsOptions,
} from "../client/@tanstack/react-query.gen";
import { ArrowIcon, ChevronIcon, DocIcon, PlaneIcon, ShieldIcon } from "../components/icons";
import { ComparisonRow } from "../features/compare/ComparisonRow";
import { ListState } from "../features/compare/ListState";
import { IncidentRow } from "../features/incident/IncidentRow";

export const Route = createFileRoute("/_authed/")({
  component: HomePage,
});

/** 首頁只列前 3 筆；多要 1 筆是為了知道要不要顯示「看全部」。 */
const SHOWN = 3;

function EntryCard({
  to,
  icon,
  title,
  children,
}: {
  to: "/compare/new" | "/incident/new";
  icon: ReactNode;
  title: string;
  children: ReactNode;
}) {
  return (
    <Link
      to={to}
      className="flex min-h-[116px] items-center rounded-2xl border border-line/60 bg-white py-5 pr-4 shadow-card transition hover:border-leaf hover:shadow-card-hover md:min-h-[182px] md:rounded-3xl md:py-7 md:pr-[30px]"
    >
      <span className="flex w-16 flex-none justify-center text-leaf md:w-[116px] [&_svg]:size-9 md:[&_svg]:size-16">
        {icon}
      </span>
      <span className="flex min-h-[116px] flex-1 flex-col justify-center border-l border-line py-0.5 pl-4 md:min-h-[140px] md:py-1.5 md:pl-[25px]">
        <span className="text-lg font-bold leading-[27px] text-heading md:text-2xl md:leading-9">
          {title}
        </span>
        <span className="mt-1.5 text-sm leading-[22px] text-ink md:mt-2 md:text-lg md:leading-[29px]">
          {children}
        </span>
      </span>
      <span className="ml-2 grid size-8 flex-none place-items-center rounded-full bg-leaf text-white md:ml-4 md:size-10">
        <ArrowIcon className="size-[22px]" />
      </span>
    </Link>
  );
}

/** 0-1 首頁：兩個入口，加上最近操作過的比較紀錄。 */
function HomePage() {
  return (
    <main data-page-paper className="-mx-2 space-y-6 py-4 font-ui leading-[26px] md:mx-0 md:p-6">
      <h1 className="sr-only">首頁</h1>
      <div className="grid gap-4 md:grid-cols-2 md:gap-6">
        <EntryCard to="/compare/new" icon={<PlaneIcon />} title="出發前：幫我選方案">
          比較多家旅遊保險方案，
          <br />
          推薦適合的保障與保額。
        </EntryCard>
        <EntryCard to="/incident/new" icon={<ShieldIcon />} title="出事了：幫我處理理賠">
          整理可能適用的理賠項目、
          <br />
          待辦與文件，並協助送件。
        </EntryCard>
        <RecentComparisons />
        <MyIncidents />
      </div>
      {import.meta.env.DEV && (
        <p>
          <Link to="/dev" className="text-blue-700 underline">
            開發工具（API 測試台、條文瀏覽、健康狀態）
          </Link>
        </p>
      )}
    </main>
  );
}

/** 「最近的比較」卡片；載入中與錯誤只在卡片內顯示，不擋入口卡。 */
function RecentComparisons() {
  const recent = useQuery(listRecentComparisonsOptions({ query: { limit: SHOWN + 1 } }));
  const comparisons = recent.data ?? [];

  return (
    <section
      aria-labelledby="recent-comparisons"
      className="mt-2 rounded-2xl border border-line/60 bg-white px-3 pt-4 pb-2 shadow-card md:mt-0 md:rounded-3xl md:px-4 md:pt-5 md:pb-3"
    >
      <div className="flex items-center gap-2.5 border-b border-line pt-1 pb-3.5 pl-1 md:gap-3.5 md:pt-0 md:pb-[18px] md:pl-2">
        <DocIcon className="size-7 flex-none text-leaf md:size-9" />
        <h2
          id="recent-comparisons"
          className="text-xl font-bold leading-[30px] text-heading md:text-2xl md:leading-9"
        >
          最近的比較
        </h2>
        {comparisons.length > SHOWN && (
          <Link
            to="/compare"
            className="ml-auto flex items-center gap-1.5 text-xs font-bold leading-[18px] text-leaf md:gap-3.5 md:text-base md:leading-6"
          >
            看全部
            <ChevronIcon className="size-4" />
          </Link>
        )}
      </div>
      <ListState
        isPending={recent.isPending}
        error={recent.error}
        isEmpty={comparisons.length === 0}
        errorText="讀取不到最近的比較，請稍後再試。"
        emptyText="比較過的方案會自動存在這裡"
      >
        <div>
          {comparisons.slice(0, SHOWN).map((c) => (
            <ComparisonRow key={c.id} comparison={c} />
          ))}
        </div>
      </ListState>
    </section>
  );
}

/** 「我的理賠」卡片（最近 3 筆事件）；載入中與錯誤只在卡片內顯示，不擋入口卡。 */
function MyIncidents() {
  const incidents = useQuery(listIncidentsOptions({ query: { limit: SHOWN } }));
  const list = incidents.data ?? [];

  return (
    <section
      aria-labelledby="my-incidents"
      className="rounded-2xl border border-line/60 bg-white px-3 pt-4 pb-2 shadow-card md:mt-0 md:rounded-3xl md:px-4 md:pt-5 md:pb-3"
    >
      <div className="flex items-center gap-2.5 border-b border-line pt-1 pb-3.5 pl-1 md:gap-3.5 md:pt-0 md:pb-[18px] md:pl-2">
        <ShieldIcon className="size-7 flex-none text-leaf md:size-9" />
        <h2
          id="my-incidents"
          className="text-xl font-bold leading-[30px] text-heading md:text-2xl md:leading-9"
        >
          我的理賠
        </h2>
      </div>
      <ListState
        isPending={incidents.isPending}
        error={incidents.error}
        isEmpty={list.length === 0}
        errorText="讀取不到我的理賠，請稍後再試。"
        emptyText="處理過的理賠會自動存在這裡"
      >
        <div>
          {list.map((i) => (
            <IncidentRow key={i.id} incident={i} />
          ))}
        </div>
      </ListState>
    </section>
  );
}
