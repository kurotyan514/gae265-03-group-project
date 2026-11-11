import { useQuery } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import { listIncidentsOptions } from "../client/@tanstack/react-query.gen";
import { ListState } from "../features/compare/ListState";
import { IncidentRow } from "../features/incident/IncidentRow";

export const Route = createFileRoute("/_authed/incident/")({
  component: AllIncidentsPage,
});

/**
 * 全部理賠（#208）：不帶 limit 列出全部事件（首頁「我的理賠」「看全部」的去處）。
 * 每列、排序與點擊行為同首頁（最後操作時間新到舊，一律進事件的第一步），不分頁，已完成的也列。
 * 規格書 v3.8 把首頁改成以行程為單位的「我的行程」與 0-6「全部行程」，採用後由那一頁取代這頁。
 */
function AllIncidentsPage() {
  const all = useQuery(listIncidentsOptions());
  const incidents = all.data ?? [];

  return (
    <main
      data-page-paper
      className="-mx-2 max-w-[1040px] space-y-6 py-4 font-ui leading-[26px] md:mx-auto md:p-6"
    >
      <header>
        <Link to="/" className="text-base font-bold leading-6 text-muted hover:text-brand">
          首頁
        </Link>
        <h1 className="mt-1 text-2xl font-bold leading-9 text-heading md:text-[30px] md:leading-[45px]">
          全部理賠
        </h1>
        {all.data && (
          <p
            className="mt-1.5 text-sm leading-[22px] text-muted md:text-lg md:leading-7"
            data-testid="all-incidents-count"
          >
            共 {incidents.length} 筆，依最後操作時間由新到舊
          </p>
        )}
      </header>
      <section
        aria-label="全部理賠"
        className="rounded-2xl border border-line/60 bg-white px-3 pt-4 pb-2 shadow-card md:rounded-3xl md:px-4 md:pt-5 md:pb-3"
      >
        <ListState
          isPending={all.isPending}
          error={all.error}
          isEmpty={incidents.length === 0}
          errorText="讀取不到理賠紀錄，請稍後再試。"
          emptyText="處理過的理賠會自動存在這裡"
        >
          {incidents.map((i) => (
            <IncidentRow key={i.id} incident={i} />
          ))}
        </ListState>
      </section>
      <div>
        <Link
          to="/"
          className="inline-flex min-h-12 items-center justify-center rounded-xl border border-line bg-white px-4 text-sm leading-[22px] font-bold text-brand hover:border-brand md:px-7 md:text-base md:leading-6"
        >
          回首頁
        </Link>
      </div>
    </main>
  );
}
