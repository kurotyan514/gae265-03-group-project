import { Button } from "@base-ui/react/button";
import { useQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { healthOptions } from "../client/@tanstack/react-query.gen";

export const Route = createFileRoute("/")({
  component: HealthPage,
});

/** 首頁：顯示後端 health endpoint 的結果。data-testid 給 e2e 冒煙測試用。 */
function HealthPage() {
  const { data, error, isPending, isFetching, refetch } = useQuery(healthOptions());

  return (
    <main className="space-y-4">
      <h1 className="text-2xl font-bold">系統健康狀態</h1>
      {/* 503 時錯誤是後端回的 body（含哪一項壞掉），直接顯示 */}
      {error && (
        <p role="alert" className="text-red-600">
          無法取得健康狀態：{JSON.stringify(error)}
        </p>
      )}
      {isPending && !error && <p>讀取中…</p>}
      {data && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
          <dt className="font-medium">後端</dt>
          <dd data-testid="health-status">{data.status}</dd>
          <dt className="font-medium">資料庫</dt>
          <dd data-testid="health-db">{data.db}</dd>
          <dt className="font-medium">pgvector</dt>
          <dd data-testid="health-pgvector">{data.pgvector}</dd>
        </dl>
      )}
      <Button
        onClick={() => void refetch()}
        disabled={isFetching}
        className="rounded-md border px-3 py-1 hover:bg-gray-100 data-[disabled]:opacity-50"
      >
        重新檢查
      </Button>
    </main>
  );
}
