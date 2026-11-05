import { Button } from "@base-ui/react/button";
import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { checkBundle, confirmBundle, ingestBundle, updateBundle } from "../../client";
import type { BundleJobOut, CheckOut, SectionBody, SplitOut } from "../../client/types.gen";

const STATUS_LABEL: Record<string, string> = { draft: "草稿", confirmed: "已確認" };

function errorText(error: unknown, status?: number): string {
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  return typeof detail === "string" ? detail : `處理失敗（HTTP ${status ?? "?"}）`;
}

/**
 * 合訂本拆分清單的確認畫面：偵測出來的各險種起點，管理者逐一改名、填代碼、標成不收、
 * 勾選要收的章、補漏掉的區段。儲存時後端會試切，標題找不到就不存。
 */
export function BundleEditor({
  split,
  onSaved,
}: {
  split: SplitOut;
  /** 後端回傳最新的清單（儲存、確認之後） */
  onSaved: (split: SplitOut) => void;
}) {
  const [company, setCompany] = useState(split.company);
  const [looseArticle, setLooseArticle] = useState(split.loose_article);
  const [sections, setSections] = useState<SectionBody[]>(split.sections);
  const [dirty, setDirty] = useState(false);
  const [check, setCheck] = useState<CheckOut | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [jobs, setJobs] = useState<BundleJobOut[]>([]);
  const [adding, setAdding] = useState({ page: "", anchor: "", name: "" });
  const path = { split_id: split.id };

  function change(index: number, patch: Partial<SectionBody>) {
    setSections((prev) => prev.map((s, i) => (i === index ? { ...s, ...patch } : s)));
    setDirty(true);
    setMessage(null);
  }

  async function run<T>(work: () => Promise<T>) {
    setBusy(true);
    setError(null);
    try {
      return await work();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function save(): Promise<SplitOut | undefined> {
    return run(async () => {
      const {
        data,
        error: err,
        response,
      } = await updateBundle({
        path,
        body: { company, loose_article: looseArticle, sections },
      });
      if (!data) {
        setError(errorText(err, response?.status));
        return undefined;
      }
      setSections(data.sections);
      setDirty(false);
      setMessage("已儲存（回到草稿，要重新確認）");
      onSaved(data);
      return data;
    });
  }

  async function tryCut() {
    if (dirty && !(await save())) return;
    await run(async () => {
      const { data, error: err, response } = await checkBundle({ path });
      if (data) setCheck(data);
      else setError(errorText(err, response?.status));
    });
  }

  async function confirm() {
    if (dirty && !(await save())) return;
    await run(async () => {
      const { data, error: err, response } = await confirmBundle({ path });
      if (!data) return setError(errorText(err, response?.status));
      setProblems(data.problems);
      onSaved(data.split);
      setSections(data.split.sections);
      setMessage(data.confirmed ? "已確認：之後上傳同一份合訂本會直接沿用這份清單" : null);
    });
  }

  async function ingest() {
    await run(async () => {
      const { data, error: err, response } = await ingestBundle({ path });
      if (data) setJobs(data);
      else setError(errorText(err, response?.status));
    });
  }

  function addSection() {
    const page = Number(adding.page);
    if (!Number.isInteger(page) || page < 1 || !adding.anchor.trim() || !adding.name.trim()) {
      setError("補區段要填頁碼、標題行開頭的文字和名稱");
      return;
    }
    setError(null);
    const created: SectionBody = {
      code: "",
      name: adding.name.trim(),
      page,
      anchor: adding.anchor.trim(),
      skip: false,
      approval_no: null,
      approval_date: null,
      chapters: {},
      exclude_chapters: [],
      policy_codes: {},
      preview: [],
    };
    // 順序要和 PDF 一致：插在第一個頁碼比它大的區段前面
    const at = sections.findIndex((s) => s.page > page);
    setSections((prev) =>
      at === -1 ? [...prev, created] : [...prev.slice(0, at), created, ...prev.slice(at)],
    );
    setAdding({ page: "", anchor: "", name: "" });
    setDirty(true);
  }

  const checkOf = (index: number) => check?.sections.find((c) => c.index === index);

  return (
    <div className="space-y-4" data-testid="bundle-editor">
      <div className="flex flex-wrap items-center gap-3">
        <p className="font-medium">{split.filename}</p>
        <span
          data-testid="split-status"
          className={`rounded px-2 py-0.5 text-sm ${
            split.status === "confirmed"
              ? "bg-green-100 text-green-900"
              : "bg-amber-100 text-amber-900"
          }`}
        >
          {STATUS_LABEL[split.status] ?? split.status}
        </span>
        {dirty && <span className="text-sm text-amber-800">有未儲存的修改</span>}
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <label className="space-y-1">
          <span className="block text-sm">保險公司</span>
          <input
            value={company}
            onChange={(e) => {
              setCompany(e.target.value);
              setDirty(true);
            }}
            placeholder="華南產物"
            className="rounded-md border px-2 py-1"
            data-testid="company"
          />
        </label>
        <label className="flex items-center gap-2 pb-1 text-sm">
          <input
            type="checkbox"
            checked={looseArticle}
            onChange={(e) => {
              setLooseArticle(e.target.checked);
              setDirty(true);
            }}
          />
          條號與標題黏在一起（例如「第一條【保險範圍】」）
        </label>
      </div>

      <ol className="space-y-3">
        {sections.map((s, i) => {
          const c = checkOf(i);
          return (
            <li
              // 區段順序就是 PDF 順序，頁碼加標題在同一份清單內是唯一的
              key={`${s.page}-${s.anchor}`}
              className={`space-y-2 rounded-md border p-3 ${s.skip ? "bg-gray-50 text-gray-600" : ""}`}
              data-testid={`section-${i}`}
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-sm">#{i + 1}</span>
                <span className="text-sm">第 {s.page} 頁</span>
                <span className="text-sm text-gray-600">{s.anchor}</span>
                {c && !s.skip && (
                  <span className="rounded bg-blue-50 px-1.5 py-0.5 text-sm text-blue-900">
                    切出 {c.articles} 條
                  </span>
                )}
                <label className="ml-auto flex items-center gap-1 text-sm">
                  <input
                    type="checkbox"
                    checked={!s.skip}
                    onChange={(e) => change(i, { skip: !e.target.checked })}
                    data-testid={`include-${i}`}
                  />
                  收錄
                </label>
                <Button
                  type="button"
                  onClick={() => {
                    setSections((prev) => prev.filter((_, k) => k !== i));
                    setDirty(true);
                  }}
                  className="rounded-md border px-2 py-0.5 text-sm hover:bg-gray-100"
                >
                  刪除區段
                </Button>
              </div>

              <div className="grid gap-2 sm:grid-cols-[1fr_12rem]">
                <label className="space-y-1">
                  <span className="block text-sm">名稱</span>
                  <input
                    value={s.name}
                    onChange={(e) => change(i, { name: e.target.value })}
                    className="w-full rounded-md border px-2 py-1"
                    data-testid={`name-${i}`}
                  />
                </label>
                {!s.skip && (
                  <label className="space-y-1">
                    <span className="block text-sm">險種代碼</span>
                    <input
                      value={s.code}
                      onChange={(e) => change(i, { code: e.target.value })}
                      placeholder="HUANAN01"
                      className="w-full rounded-md border px-2 py-1 font-mono"
                      data-testid={`code-${i}`}
                    />
                  </label>
                )}
              </div>

              {(s.preview ?? []).length > 0 && (
                <details className="text-sm">
                  <summary className="cursor-pointer">標題後的前幾行</summary>
                  <ul className="mt-1 list-disc pl-5 text-gray-700">
                    {(s.preview ?? []).map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                </details>
              )}

              {!s.skip && c && c.chapters.length > 0 && (
                <div className="space-y-1 text-sm" data-testid={`chapters-${i}`}>
                  <p className="text-gray-600">
                    章（取消勾選就不收；保單代碼選填，保單上傳用它對到這一章）
                  </p>
                  {c.chapters.map((ch) => {
                    const excluded = (s.exclude_chapters ?? []).includes(ch.name);
                    return (
                      <div key={ch.name} className="flex flex-wrap items-center gap-2">
                        <label className="flex items-center gap-1">
                          <input
                            type="checkbox"
                            checked={!excluded}
                            onChange={(e) =>
                              change(i, {
                                exclude_chapters: e.target.checked
                                  ? (s.exclude_chapters ?? []).filter((n) => n !== ch.name)
                                  : [...(s.exclude_chapters ?? []), ch.name],
                              })
                            }
                          />
                          {ch.name || "（沒有章）"}（{ch.articles} 條）
                        </label>
                        {!excluded && (
                          <input
                            value={(s.policy_codes ?? {})[ch.name] ?? ""}
                            onChange={(e) =>
                              change(i, {
                                policy_codes: {
                                  ...(s.policy_codes ?? {}),
                                  [ch.name]: e.target.value,
                                },
                              })
                            }
                            placeholder="保單代碼"
                            aria-label={`${ch.name}的保單代碼`}
                            className="w-28 rounded-md border px-2 py-0.5 font-mono"
                          />
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </li>
          );
        })}
      </ol>

      <fieldset className="space-y-2 rounded-md border border-dashed p-3">
        <legend className="px-1 text-sm">偵測漏掉了？手動補一個區段</legend>
        <div className="flex flex-wrap items-end gap-2">
          <input
            value={adding.page}
            onChange={(e) => setAdding({ ...adding, page: e.target.value })}
            placeholder="頁碼"
            inputMode="numeric"
            aria-label="補區段的頁碼"
            className="w-20 rounded-md border px-2 py-1"
            data-testid="add-page"
          />
          <input
            value={adding.anchor}
            onChange={(e) => setAdding({ ...adding, anchor: e.target.value })}
            placeholder="標題行開頭的文字"
            aria-label="補區段的標題行"
            className="min-w-48 flex-1 rounded-md border px-2 py-1"
            data-testid="add-anchor"
          />
          <input
            value={adding.name}
            onChange={(e) => setAdding({ ...adding, name: e.target.value })}
            placeholder="名稱"
            aria-label="補區段的名稱"
            className="min-w-40 flex-1 rounded-md border px-2 py-1"
            data-testid="add-name"
          />
          <Button
            type="button"
            onClick={addSection}
            className="rounded-md border px-3 py-1 hover:bg-gray-100"
            data-testid="add-section"
          >
            補上
          </Button>
        </div>
      </fieldset>

      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          onClick={save}
          disabled={busy || !dirty}
          className="rounded-md border px-3 py-1 disabled:opacity-50"
          data-testid="save"
        >
          儲存
        </Button>
        <Button
          type="button"
          onClick={tryCut}
          disabled={busy}
          className="rounded-md border px-3 py-1 disabled:opacity-50"
          data-testid="try-cut"
        >
          試切（看每個區段切出幾條）
        </Button>
        <Button
          type="button"
          onClick={confirm}
          disabled={busy}
          className="rounded-md bg-gray-900 px-3 py-1 text-white disabled:opacity-50"
          data-testid="confirm"
        >
          確認這份清單
        </Button>
      </div>

      {split.status === "confirmed" && !dirty && (
        <div className="space-y-2 rounded-md border p-3" data-testid="ingest-panel">
          <p className="text-sm">
            清單已確認。入庫會為每個收錄的險種各建一個上傳工作：各自驗證（範圍限定在自己的標題之間），
            通過的條文入庫，其餘成為待確認條文，到「單一險種上傳」頁處理。
          </p>
          <Button
            type="button"
            onClick={ingest}
            disabled={busy}
            className="rounded-md bg-gray-900 px-3 py-1 text-white disabled:opacity-50"
            data-testid="ingest"
          >
            入庫
          </Button>
          {jobs.length > 0 && (
            <div data-testid="ingest-jobs">
              <p className="text-sm text-green-800">
                已建立 {jobs.length} 個入庫工作，在背景依序處理；進度與待確認條文請到{" "}
                <Link to="/admin/ingest" className="underline">
                  單一險種上傳
                </Link>{" "}
                頁看：
              </p>
              <ul className="list-disc pl-5 text-sm">
                {jobs.map((j) => (
                  <li key={j.job_id}>
                    {j.code} {j.name}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {message && (
        <p className="text-green-800" data-testid="bundle-message">
          {message}
        </p>
      )}
      {check && !check.ok && (
        <p role="alert" className="text-red-700" data-testid="check-error">
          {check.error}
        </p>
      )}
      {problems.length > 0 && (
        <ul className="list-disc pl-5 text-red-700" data-testid="problems">
          {problems.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      )}
      {error && (
        <p role="alert" className="text-red-700" data-testid="bundle-error">
          {error}
        </p>
      )}
    </div>
  );
}
