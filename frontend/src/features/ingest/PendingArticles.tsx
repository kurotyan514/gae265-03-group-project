import { Button } from "@base-ui/react/button";
import { useState } from "react";
import { deletePendingArticle, editPendingArticle, releasePendingArticle } from "../../client";
import type { IngestJobDetail, PendingArticleOut } from "../../client/types.gen";

type Finding = {
  rule?: string;
  status?: string;
  severity?: string;
  message?: string;
  suggestion?: string;
  evidence?: Record<string, unknown>;
};

const STATUS_LABEL: Record<string, string> = {
  pending: "待處理",
  released: "已放行",
  deleted: "已刪除",
};

function evidenceText(value: unknown): string {
  return typeof value === "string" ? value : JSON.stringify(value);
}

/** 錯誤訊息：FastAPI 的 detail 是字串；其他情況（網路、驗證）給通用說明。 */
function errorText(error: unknown, status?: number): string {
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  if (typeof detail === "string") return detail;
  return `處理失敗（HTTP ${status ?? "?"}）`;
}

/**
 * 內容驗證沒通過的條文（待確認條文）：管理者逐條看原因，決定放行、改字後放行或刪除。
 * 處理結果由後端回傳整個工作的最新狀態，交給 onChange 更新畫面。
 */
export function PendingArticles({
  jobId,
  articles,
  onChange,
}: {
  jobId: string;
  articles: PendingArticleOut[];
  onChange: (detail: IngestJobDetail) => void;
}) {
  const pending = articles.filter((a) => a.status === "pending");
  const done = articles.filter((a) => a.status !== "pending");
  if (articles.length === 0) return null;

  return (
    <section className="space-y-3" aria-label="待確認條文" data-testid="pending-articles">
      <h2 className="text-lg font-medium">
        待確認條文：{pending.length} 條待處理
        {done.length > 0 && (
          <span className="ml-2 text-sm font-normal text-gray-600">已處理 {done.length} 條</span>
        )}
      </h2>
      <p className="text-sm text-gray-600">
        這些條文沒有通過內容驗證，還沒寫入資料庫。放行是只為這一條算向量並寫入；改字後放行視為你已確認，不再重新驗證，舊字、新字與原因會記在事件紀錄。
      </p>
      <ul className="space-y-2">
        {pending.map((article) => (
          <PendingItem
            key={article.article_no}
            jobId={jobId}
            article={article}
            onChange={onChange}
          />
        ))}
      </ul>
      {done.length > 0 && (
        <ul className="space-y-1 text-sm text-gray-600" data-testid="processed-articles">
          {done.map((a) => (
            <li key={a.article_no}>
              第 {a.article_no} 條 {a.title}：{STATUS_LABEL[a.status] ?? a.status}
              {a.edited && "（已改字）"}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function PendingItem({
  jobId,
  article,
  onChange,
}: {
  jobId: string;
  article: PendingArticleOut;
  onChange: (detail: IngestJobDetail) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [content, setContent] = useState(article.content);
  const [title, setTitle] = useState(article.title);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const findings = article.findings as Finding[];
  const path = { job_id: jobId, article_no: article.article_no };

  async function run(
    call: () => Promise<{ data?: IngestJobDetail; error?: unknown; response?: Response }>,
  ) {
    setBusy(true);
    setError(null);
    try {
      const { data, error: err, response } = await call();
      if (data) onChange(data);
      else setError(errorText(err, response?.status));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <li
      className="space-y-2 rounded-md border border-amber-500 bg-amber-50 p-3"
      data-testid={`pending-${article.article_no}`}
    >
      <p className="font-medium">
        第 {article.article_no} 條　{article.title}
        <span className="ml-2 text-sm font-normal text-gray-600">
          {article.chapter} · 第 {article.page_start}
          {article.page_end !== article.page_start && `–${article.page_end}`} 頁
        </span>
      </p>

      {findings.length > 0 && (
        <ul className="list-disc space-y-1 pl-5 text-sm" data-testid="findings">
          {findings.map((f) => (
            <li key={`${f.rule}-${f.message}`}>
              <span className="mr-1 rounded bg-white px-1.5 py-0.5 text-xs">
                {f.status === "FAIL" ? "確定錯誤" : "工具不確定"} · {f.rule}
              </span>
              {f.message}
              {f.suggestion && <span className="text-gray-700">（建議：{f.suggestion}）</span>}
              {f.evidence && Object.keys(f.evidence).length > 0 && (
                <dl className="mt-1 grid gap-x-2 gap-y-0.5 text-xs text-gray-700 sm:grid-cols-[auto_1fr]">
                  {Object.entries(f.evidence).map(([k, v]) => (
                    <div key={k} className="contents">
                      <dt className="font-mono">{k}</dt>
                      <dd className="font-mono break-words whitespace-pre-wrap">
                        {evidenceText(v)}
                      </dd>
                    </div>
                  ))}
                </dl>
              )}
            </li>
          ))}
        </ul>
      )}

      <details>
        <summary className="cursor-pointer text-sm">
          入庫內容（{article.content.length} 字）
        </summary>
        <pre className="mt-1 max-h-72 overflow-auto rounded bg-white p-2 text-sm whitespace-pre-wrap">
          {article.content}
        </pre>
      </details>

      {editing ? (
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            run(() =>
              editPendingArticle({
                path,
                body: { content, title: title === article.title ? null : title, reason },
              }),
            );
          }}
        >
          <label className="block space-y-1">
            <span className="text-sm">標題</span>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full rounded-md border px-2 py-1"
            />
          </label>
          <label className="block space-y-1">
            <span className="text-sm">條文內容</span>
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              rows={10}
              required
              className="w-full rounded-md border px-2 py-1 font-mono text-sm"
              data-testid="edit-content"
            />
          </label>
          <label className="block space-y-1">
            <span className="text-sm">為什麼這樣改（必填）</span>
            <input
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              required
              placeholder="例如：實際保單的寫法"
              className="w-full rounded-md border px-2 py-1"
              data-testid="edit-reason"
            />
          </label>
          <div className="flex gap-2">
            <Button
              type="submit"
              disabled={busy || !content.trim() || !reason.trim()}
              className="rounded-md bg-gray-900 px-3 py-1 text-white disabled:opacity-50"
              data-testid="edit-submit"
            >
              改字後放行
            </Button>
            <Button
              type="button"
              disabled={busy}
              onClick={() => setEditing(false)}
              className="rounded-md border bg-white px-3 py-1"
            >
              取消
            </Button>
          </div>
        </form>
      ) : (
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            disabled={busy}
            onClick={() => run(() => releasePendingArticle({ path }))}
            className="rounded-md bg-gray-900 px-3 py-1 text-white disabled:opacity-50"
            data-testid="release"
          >
            放行
          </Button>
          <Button
            type="button"
            disabled={busy}
            onClick={() => setEditing(true)}
            className="rounded-md border bg-white px-3 py-1 disabled:opacity-50"
            data-testid="edit"
          >
            改字後放行
          </Button>
          <Button
            type="button"
            disabled={busy}
            onClick={() => run(() => deletePendingArticle({ path }))}
            className="rounded-md border border-red-700 bg-white px-3 py-1 text-red-700 disabled:opacity-50"
            data-testid="delete"
          >
            刪除
          </Button>
        </div>
      )}
      {error && (
        <p role="alert" className="text-red-700" data-testid="pending-error">
          {error}
        </p>
      )}
    </li>
  );
}
