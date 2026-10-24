import { useEffect, useState } from "react";

type HealthStatus = { status: string; db: string; pgvector: string };

// ponytail: 直接 fetch；#4 改用產生的 API client 與 TanStack Query
export function App() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/v1/health")
      .then((res) => res.json() as Promise<HealthStatus>)
      .then(setHealth)
      .catch((err: unknown) => setError(String(err)));
  }, []);

  return (
    <main>
      <h1>系統健康狀態</h1>
      {error && <p role="alert">無法取得健康狀態：{error}</p>}
      {!health && !error && <p>讀取中…</p>}
      {health && (
        <dl>
          <dt>後端</dt>
          <dd data-testid="health-status">{health.status}</dd>
          <dt>資料庫</dt>
          <dd data-testid="health-db">{health.db}</dd>
          <dt>pgvector</dt>
          <dd data-testid="health-pgvector">{health.pgvector}</dd>
        </dl>
      )}
    </main>
  );
}
