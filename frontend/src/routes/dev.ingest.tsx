import { Button } from "@base-ui/react/button";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { type FormEvent, useEffect, useState } from "react";
import { getIngestJob } from "../client";
import { listIngestJobsOptions } from "../client/@tanstack/react-query.gen";
import type { IngestEventOut, IngestJobOut } from "../client/types.gen";
import { ProgressTrack } from "../features/ingest/ProgressTrack";
import { KIND_LABEL, STEPS } from "../features/ingest/steps";
import { usePacedEvents } from "../features/ingest/usePacedEvents";

type IngestSearch = { demo?: 1; speed?: number };

export const Route = createFileRoute("/dev/ingest")({
  // ?demo=1 開啟示範模式；?speed=2 調整示範的播放倍速（預設 1）
  validateSearch: (search: Record<string, unknown>): IngestSearch => ({
    demo: search.demo === 1 || search.demo === "1" || search.demo === true ? 1 : undefined,
    speed:
      typeof search.speed === "number" && search.speed > 0
        ? Math.min(search.speed, 100)
        : undefined,
  }),
  component: IngestPage,
});

const STATUS_LABEL: Record<string, string> = {
  running: "處理中",
  done: "完成",
  rejected: "不是條款",
  needs_review: "待人工確認",
  failed: "失敗",
};

const ICON: Record<string, string> = { running: "⏳", ok: "✅", warning: "⚠️", error: "❌" };

type Issue = { level: string; message: string };

/** 已經處理完（或停在等人工確認）的工作可以重播；處理中的工作不行。 */
const REPLAYABLE = new Set(["done", "failed", "rejected", "needs_review"]);

/** 上傳條款 PDF，由後端 ingest agent 依序判斷、切塊、驗證、算向量並入庫；進度用 SSE 即時顯示。 */
function IngestPage() {
  const queryClient = useQueryClient();
  const jobs = useQuery({ ...listIngestJobsOptions(), refetchInterval: 5000 });
  const [selected, setSelected] = useState<string | null>(null);
  // 剛在這個頁面上傳的工作：即使讀到時已經結束，也要從頭演出；改選別筆就不算了
  const [uploadedId, setUploadedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [round, setRound] = useState(0); // 人工確認後遞增，讓進度元件重新讀取並訂閱
  const { demo, speed } = Route.useSearch();
  const navigate = Route.useNavigate();
  const demoOn = demo === 1;
  // 示範模式下，選取中那筆在左邊清單顯示的狀態要和右邊一樣，動畫演完才揭曉結果
  const [shownStatus, setShownStatus] = useState<string | null>(null);

  function toggleDemo() {
    navigate({ search: (prev) => ({ ...prev, demo: demoOn ? undefined : 1 }) });
  }

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
      setUploadedId(job.id);
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
      <div className="flex items-center gap-2">
        <button
          type="button"
          role="switch"
          aria-checked={demoOn}
          onClick={toggleDemo}
          data-testid="demo-toggle"
          className={`rounded-full border px-3 py-1 text-sm ${
            demoOn ? "border-gray-900 bg-gray-900 text-white" : "bg-white text-gray-700"
          }`}
        >
          示範模式：{demoOn ? "開" : "關"}
        </button>
        <span className="text-sm text-gray-500">
          慢速逐步演出 agent 呼叫的工具，供報告示範用；不影響後端處理
        </span>
      </div>

      <form onSubmit={submit} className="flex flex-wrap items-end gap-3" data-testid="upload-form">
        <label className="space-y-1">
          <span className="block font-medium">條款 PDF</span>
          <input type="file" name="file" accept="application/pdf" required data-testid="file" />
        </label>
        <label className="space-y-1">
          <span className="block font-medium">保險公司</span>
          <input
            name="company"
            required
            defaultValue="富邦產物"
            title="必須是 PDF 商品標題行的開頭，例如「國泰產物新旅行平安保障保險」填「國泰產物」"
            className="rounded-md border px-2 py-1"
          />
        </label>
        <label className="space-y-1">
          <span className="block font-medium">險種代碼</span>
          <input
            name="insurance_code"
            required
            placeholder="FUBON07"
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
                onClick={() => {
                  if (job.id !== selected) setUploadedId(null);
                  setSelected(job.id);
                }}
                className={`w-full rounded-md border px-3 py-2 text-left hover:bg-gray-100 ${
                  selected === job.id ? "border-gray-900" : ""
                }`}
              >
                <span className="block font-medium">{job.filename}</span>
                <span className="text-sm text-gray-600">
                  {job.insurance_code} · {(() => {
                    const s =
                      demoOn && selected === job.id && shownStatus ? shownStatus : job.status;
                    return STATUS_LABEL[s] ?? s;
                  })()}
                </span>
              </button>
            </li>
          ))}
        </ul>

        {selected ? (
          <JobProgress
            key={`${selected}-${round}`}
            jobId={selected}
            demo={demoOn}
            speed={speed ?? 1}
            fresh={selected === uploadedId}
            onShownStatus={setShownStatus}
            onApprove={() => setRound((n) => n + 1)}
          />
        ) : (
          <p className="text-gray-500">上傳檔案或從左邊選一筆紀錄，就能看到 agent 的處理進度。</p>
        )}
      </div>
    </section>
  );
}

/** 先讀已發生的事件（重整後回看），再用 SSE 接續；以 seq 去重，EventSource 自動重連也不會重複。 */
function JobProgress({
  jobId,
  demo,
  speed,
  fresh,
  onShownStatus,
  onApprove,
}: {
  jobId: string;
  demo: boolean;
  speed: number;
  /** 這是剛在這個頁面上傳的工作 */
  fresh: boolean;
  onShownStatus: (status: string) => void;
  onApprove: () => void;
}) {
  const queryClient = useQueryClient();
  const [received, setEvents] = useState<IngestEventOut[]>([]);
  const [status, setStatus] = useState("running");
  // 打開時還在處理中（或剛上傳）的工作，全程慢速演出；已經處理完的工作直接顯示結果，要演再按「重播」。
  // live 與 replaying 只在「一次演出」期間為 true，演完就清掉，之後切換示範模式不會再自己重演。
  const [live, setLive] = useState(false);
  const [replaying, setReplaying] = useState(false);
  const [runs, setRuns] = useState(0); // 重播次數，只增不減：讓軌道重新掛載、節奏重新開始
  const [wasFresh] = useState(fresh);
  const paced = demo && (live || replaying);
  // 示範模式只改變事件「何時顯示」，資料仍是後端已存的事件，重播也不重新讀取
  const events = usePacedEvents(received, { enabled: paced, speed, restart: runs });
  // 慢速演出時，事件還沒演完就先顯示「處理中」：最終狀態與確認按鈕要等小人走到才出現，
  // 否則老師會在小人還在第一站時就看到「完成」或可以按的按鈕
  const drained = !paced || events.length >= received.length;
  const shownStatus = drained ? status : "running";
  useEffect(() => onShownStatus(shownStatus), [shownStatus, onShownStatus]);
  const canReplay = demo && drained && REPLAYABLE.has(shownStatus);
  useEffect(() => {
    if (drained && status !== "running") {
      setLive(false);
      setReplaying(false);
    }
  }, [drained, status]);

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
      // 剛上傳的工作即使第一次讀取時已經結束，也要從頭演；要在加入事件之前，才不會先整批顯示再重演
      setLive(data.status === "running" || wasFresh);
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
  }, [jobId, queryClient, wasFresh]);

  async function approve() {
    const res = await fetch(`/api/v1/ingest/jobs/${jobId}/approve`, { method: "POST" });
    if (res.ok) onApprove();
  }

  return (
    <div className="space-y-3" data-testid="progress">
      <div className="flex items-start justify-between gap-3">
        <p>
          狀態：
          <strong data-testid="job-status">{STATUS_LABEL[shownStatus] ?? shownStatus}</strong>
        </p>
        {canReplay && (
          <Button
            type="button"
            onClick={() => {
              setRuns((n) => n + 1);
              setReplaying(true);
            }}
            className="rounded-md border px-3 py-1 text-sm hover:bg-gray-100"
            data-testid="replay"
          >
            ↻ 重播
          </Button>
        )}
      </div>
      {shownStatus === "needs_review" && (
        <div className="space-y-2 rounded-md border border-amber-500 bg-amber-50 p-3">
          <p>驗證沒有通過,條文還沒有寫入資料庫。請對照下方的錯誤,確認後可以忽略警告仍然寫入。</p>
          <Button
            type="button"
            onClick={approve}
            className="rounded-md bg-gray-900 px-3 py-1 text-white"
            data-testid="approve"
          >
            忽略警告,仍然寫入
          </Button>
        </div>
      )}
      {/* 重播時整條軌道重新掛載，小人直接回到起點，不會倒著走回去 */}
      {demo && <ProgressTrack key={runs} events={events} />}
      <ol className="space-y-2">
        {STEPS.map((step) => {
          const latest = [...events].reverse().find((e) => e.step === step.key);
          const issues = (latest?.data?.issues ?? []) as Issue[];
          const actions = (latest?.data?.actions ?? []) as string[];
          // LLM 判斷那步的理由（既有事件訊息的「：」之後），示範模式用對話氣泡呈現
          const reason =
            step.kind === "llm" && latest?.status !== "running"
              ? latest?.message.split("：").slice(1).join("：")
              : undefined;
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
                {demo && latest && (
                  <span
                    data-testid={`kind-${step.key}`}
                    className={`rounded px-1.5 py-0.5 text-xs ${
                      step.kind === "llm"
                        ? "bg-purple-100 text-purple-800"
                        : "bg-gray-100 text-gray-700"
                    }`}
                  >
                    {KIND_LABEL[step.kind]}
                  </span>
                )}
              </div>
              {demo && latest && (
                <p className="font-mono text-sm text-gray-600" data-testid={`tool-${step.key}`}>
                  🔧 呼叫 tool：{step.tool}()
                </p>
              )}
              {latest && (
                <p className="text-sm text-gray-700">
                  {demo && reason ? latest.message.split("：")[0] : latest.message}
                  {demo && latest.status === "running" && (
                    <span className="ingest-dots ml-1" aria-hidden>
                      <span>.</span>
                      <span>.</span>
                      <span>.</span>
                    </span>
                  )}
                </p>
              )}
              {demo && reason && (
                <blockquote
                  data-testid="llm-bubble"
                  className="mt-1 rounded-lg border border-purple-200 bg-purple-50 px-3 py-2 text-sm text-purple-900"
                >
                  <span className="mr-1 text-xs font-medium">LLM 回覆</span>
                  {reason}
                </blockquote>
              )}
              {latest?.total != null && latest.current != null && latest.total > 0 && (
                <progress
                  className="mt-1 w-full"
                  value={latest.current}
                  max={latest.total}
                  aria-label={`${step.label}進度`}
                />
              )}
              {actions.length > 0 && (
                <ul className="mt-1 list-disc pl-5 text-sm" data-testid="repair-actions">
                  {actions.map((a) => (
                    <li key={a}>已修復：{a}</li>
                  ))}
                </ul>
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
