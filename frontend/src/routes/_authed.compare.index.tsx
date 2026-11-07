import { useQuery } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import { listRecentComparisonsOptions } from "../client/@tanstack/react-query.gen";
import { ComparisonRow } from "../features/compare/ComparisonRow";

export const Route = createFileRoute("/_authed/compare/")({
  component: AllComparisonsPage,
});

/** 0-6 全部比較：不帶 limit 列出全部比較紀錄（首頁「看全部」的去處）。 */
function AllComparisonsPage() {
  const all = useQuery(listRecentComparisonsOptions());
  const comparisons = all.data ?? [];

  return (
    <main className="mx-auto max-w-[1040px] space-y-6 rounded-3xl bg-paper p-4 sm:p-6">
      <header>
        <Link to="/" className="text-base font-bold leading-6 text-muted hover:text-brand">
          首頁
        </Link>
        <h1 className="mt-1 text-2xl font-bold leading-[45px] text-heading sm:text-[30px]">
          全部比較
        </h1>
        {all.data && (
          <p className="mt-1.5 text-base leading-7 text-muted sm:text-lg">
            共 {comparisons.length} 筆，依最後操作時間由新到舊
          </p>
        )}
      </header>
      <section className="rounded-3xl border border-line/60 bg-white px-3 py-2 shadow-card sm:px-4">
        {all.isPending ? (
          <p className="px-2 py-7 text-muted">讀取中…</p>
        ) : all.error ? (
          <p role="alert" className="px-2 py-7 text-red-600">
            讀取不到比較紀錄，請稍後再試。
          </p>
        ) : comparisons.length === 0 ? (
          <p className="px-2 py-7 text-muted">目前沒有紀錄</p>
        ) : (
          comparisons.map((c) => <ComparisonRow key={c.id} comparison={c} />)
        )}
      </section>
      <div>
        <Link
          to="/"
          className="inline-flex min-h-12 items-center justify-center rounded-xl border border-line bg-white px-7 text-base font-bold text-brand hover:border-brand"
        >
          回首頁
        </Link>
      </div>
    </main>
  );
}
