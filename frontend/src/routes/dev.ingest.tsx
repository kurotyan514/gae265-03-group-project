import { Button } from "@base-ui/react/button";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { type FormEvent, useEffect, useState } from "react";
import { getIngestJob } from "../client";
import { listIngestJobsOptions } from "../client/@tanstack/react-query.gen";
import type { IngestEventOut, IngestJobOut } from "../client/types.gen";

export const Route = createFileRoute("/dev/ingest")({
  component: IngestPage,
});

const STEPS = [
  { key: "extract", label: "讀取 PDF" },
  { key: "classify", label: "判斷是否為保險條款" },
  { key: "chunk", label: "切 chunk（一條一段）" },
  { key: "validate", label: "驗證條文" },
  { key: "embed", label: "計算 embedding" },
  { key: "import", label: "寫入資料庫" },
] as const;

const STATUS_LABEL: Record<string, string> = {
  running: "處理中",
  done: "完成",
  rejected: "不是條款",
  failed: "失敗",
};

const ICON: Record<string, string> = { running: "⏳", ok: "✅", warning: "⚠️", error: "❌" };

type Issue = { level: string; message: string };

/** 上傳條款 PDF，由後端 ingest agent 依序判斷、切塊、驗證、算向量並入庫；進度用 SSE 即時顯示。 */
function IngestPage() {
  const queryClient = useQueryClient();
  const jobs = useQuery({ ...listIngestJobsOptions(), refetchInterval: 5000 });
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const res = await fetch("/api/v1/ingest/jobs", {
        method: "POST",
        body: new FormData(e.currentTarget),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(
          typeof body?.detail === "string" ? body.detail : `上傳失敗（HTTP ${res.status}）`,
        );
      }
      const job = (await res.json()) as IngestJobOut;
      setSelected(job.id);
      await queryClient.invalidateQueries({ queryKey: listIngestJobsOptions().queryKey });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="space-y-6">
      <form onSubmit={submit} className="flex flex-wrap items-end gap-3" data-testid="upload-form">
        <label className="space-y-1">
          <span className="block font-medium">條款 PDF</span>
          <input type="file" name="file" accept="application/pdf" required data-testid="file" />
        </label>
        <label className="space-y-1">
          <span className="block font-medium">險種代碼</span>
          <input
            name="insurance_code"
            required
            placeholder="T113"
            className="rounded-md border px-2 py-1"
          />
        </label>
        <label className="space-y-1">
          <span className="block font-medium">險種名稱</span>
          <input
            name="insurance_name"
            required
            placeholder="旅遊不便險"
            className="rounded-md border px-2 py-1"
          />
        </label>
        <Button
          type="submit"
          disabled={busy}
          className="rounded-md bg-gray-900 px-3 py-1 text-white disabled:opacity-50"
        >
          上傳並處理
        </Button>
        {error && (
          <p role="alert" className="text-red-700" data-testid="upload-error">
            {error}
          </p>
        )}
      </form>

      <div className="grid gap-6 md:grid-cols-[18rem_1fr]">
        <ul className="space-y-1" aria-label="上傳紀錄" data-testid="jobs">
          {jobs.data?.length === 0 && <li className="text-gray-500">還沒有上傳紀錄</li>}
          {jobs.data?.map((job) => (
            <li key={job.id}>
              <button
                type="button"
                onClick={() => setSelected(job.id)}
                className={`w-full rounded-md border px-3 py-2 text-left hover:bg-gray-100 ${
                  selected === job.id ? "border-gray-900" : ""
                }`}
              >
                <span className="block font-medium">{job.filename}</span>
                <span className="text-sm text-gray-600">
                  {job.insurance_code} · {STATUS_LABEL[job.status] ?? job.status}
                </span>
              </button>
            </li>
          ))}
        </ul>

        {selected ? (
          <JobProgress key={selected} jobId={selected} />
        ) : (
          <p className="text-gray-500">上傳檔案或從左邊選一筆紀錄，就能看到 agent 的處理進度。</p>
        )}
      </div>
    </section>
  );
}

/** 先讀已發生的事件（重整後回看），再用 SSE 接續；以 seq 去重，EventSource 自動重連也不會重複。 */
function JobProgress({ jobId }: { jobId: string }) {
  const queryClient = useQueryClient();
  const [events, setEvents] = useState<IngestEventOut[]>([]);
  const [status, setStatus] = useState("running");

  useEffect(() => {
    let source: EventSource | undefined;
    let cancelled = false;

    const add = (incoming: IngestEventOut[]) =>
      setEvents((prev) => {
        const known = new Set(prev.map((e) => e.seq));
        const fresh = incoming.filter((e) => !known.has(e.seq));
        return fresh.length ? [...prev, ...fresh].sort((a, b) => a.seq - b.seq) : prev;
      });

    (async () => {
      const { data } = await getIngestJob({ path: { job_id: jobId } });
      if (cancelled || !data) return;
      add(data.events);
      setStatus(data.status);
      if (data.status !== "running") return;

      const after = data.events.at(-1)?.seq ?? 0;
      source = new EventSource(`/api/v1/ingest/jobs/${jobId}/events?after=${after}`);
      source.addEventListener("ingest", (m) =>
        add([JSON.parse((m as MessageEvent).data) as IngestEventOut]),
      );
      source.addEventListener("end", (m) => {
        setStatus(JSON.parse((m as MessageEvent).data).status);
        source?.close();
        queryClient.invalidateQueries({ queryKey: listIngestJobsOptions().queryKey });
      });
    })();

    return () => {
      cancelled = true;
      source?.close();
    };
  }, [jobId, queryClient]);

  return (
    <div className="space-y-3" data-testid="progress">
      <p>
        狀態：
        <strong data-testid="job-status">{STATUS_LABEL[status] ?? status}</strong>
      </p>
      <ol className="space-y-2">
        {STEPS.map((step) => {
          const latest = [...events].reverse().find((e) => e.step === step.key);
          const issues = (latest?.data?.issues ?? []) as Issue[];
          return (
            <li
              key={step.key}
              className="rounded-md border p-3"
              data-testid={`step-${step.key}`}
              data-status={latest?.status ?? "pending"}
            >
              <div className="flex items-center gap-2">
                <span aria-hidden>{latest ? ICON[latest.status] : "⚪"}</span>
                <span className="font-medium">{step.label}</span>
              </div>
              {latest && <p className="text-sm text-gray-700">{latest.message}</p>}
              {latest?.total != null && latest.current != null && latest.total > 0 && (
                <progress
                  className="mt-1 w-full"
                  value={latest.current}
                  max={latest.total}
                  aria-label={`${step.label}進度`}
                />
              )}
              {issues.length > 0 && (
                <ul className="mt-1 list-disc pl-5 text-sm">
                  {issues.map((i) => (
                    <li key={`${i.level}-${i.message}`}>
                      {i.level === "error" ? "錯誤" : "提醒"}：{i.message}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
