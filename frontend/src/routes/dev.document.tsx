import { Button } from "@base-ui/react/button";
import { createFileRoute } from "@tanstack/react-router";
import { type FormEvent, useEffect, useState } from "react";
import { listDocumentSamples } from "../client";
import type { DocumentSampleOut, WalkStep, WalkthroughOut } from "../client/types.gen";

export const Route = createFileRoute("/dev/document")({
  component: DocumentWalkthroughPage,
});

const box = "space-y-3 rounded-md border p-3";
const primary = "rounded-md bg-gray-900 px-3 py-1 text-white disabled:opacity-50";
const secondary = "rounded-md border px-3 py-1 hover:bg-gray-100 disabled:opacity-50";

const STATE_STYLE: Record<WalkStep["state"], { label: string; className: string }> = {
  ok: { label: "完成", className: "border-green-300 bg-green-50 text-green-900" },
  warn: { label: "要使用者確認", className: "border-amber-300 bg-amber-50 text-amber-900" },
  fail: { label: "停在這一步", className: "border-red-300 bg-red-50 text-red-900" },
  skip: { label: "沒有執行", className: "border-gray-200 bg-gray-50 text-gray-500" },
};

const RESULT_STYLE: Record<WalkthroughOut["status"], string> = {
  recognized: "border-green-400 bg-green-50",
  needs_review: "border-amber-400 bg-amber-50",
  failed: "border-red-400 bg-red-50",
};

/** 後端錯誤訊息（FastAPI 的 detail）轉成一行字。 */
function detailOf(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  return typeof detail === "string" ? `${status} ${detail}` : `HTTP ${status}`;
}

/**
 * 文件辨識測試台：上傳一份理賠文件，用 6 號真正的程式辨識，每按一次「下一步」看一個步驟。
 * Drive 是展示用的假雲端，檔案不會存到任何地方；畫面上的文字都已經遮過個資。
 * 展示用的事件固定是「日本 2026-07-05～07-10，班機延誤」，待辦有延誤證明、機票及登機證、理賠申請書。
 */
function DocumentWalkthroughPage() {
  const [samples, setSamples] = useState<DocumentSampleOut[]>([]);
  const [hasGrant, setHasGrant] = useState(true);
  const [draftRules, setDraftRules] = useState(false);
  const [passed, setPassed] = useState<string[]>([]);
  const [fileLabel, setFileLabel] = useState<string | null>(null);
  const [result, setResult] = useState<WalkthroughOut | null>(null);
  const [shown, setShown] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listDocumentSamples()
      .then((res) => {
        if (res.data?.length) {
          setSamples(res.data);
          return;
        }
        const status = res.response?.status;
        setError(
          status === 404
            ? "後端沒有範例文件的 API（404）：後端可能還在跑舊的程式，請重啟後端（停掉 make up 再重跑）"
            : `讀不到範例文件（${status ? `HTTP ${status}` : "後端沒有回應"}），請確認後端有開：docker compose logs --tail=50 backend`,
        );
      })
      .catch(() =>
        setError("連不到後端，請確認 make up 有在跑：docker compose logs --tail=50 backend"),
      );
  }, []);

  async function recognize(file: File, label: string) {
    setBusy(true);
    setError(null);
    setResult(null);
    setShown(0);
    setFileLabel(label);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("has_grant", String(hasGrant));
      form.append("apply_draft_rules", String(draftRules));
      for (const kind of passed) form.append("previous", kind);
      const response = await fetch("/api/v1/dev/document-walkthrough", {
        method: "POST",
        body: form,
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(detailOf(body, response.status));
      const walked = body as WalkthroughOut;
      setResult(walked);
      setShown(1);
      if (walked.status === "recognized" && walked.document_kind) {
        const kind = walked.document_kind;
        setPassed((current) => (current.includes(kind) ? current : [...current, kind]));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function pickSample(sample: DocumentSampleOut) {
    const response = await fetch(`/api/v1/dev/document-samples/${sample.name}`);
    if (!response.ok) {
      setError(`範例下載失敗（HTTP ${response.status}）`);
      return;
    }
    const blob = await response.blob();
    await recognize(
      new File([blob], `${sample.name}.pdf`, { type: "application/pdf" }),
      `範例：${sample.label}`,
    );
  }

  function uploadAction(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const file = new FormData(e.currentTarget).get("file");
    if (file instanceof File && file.size > 0) void recognize(file, file.name);
  }

  const steps = result?.steps ?? [];
  const allShown = result !== null && shown >= steps.length;

  return (
    <section className="space-y-4" data-testid="document-walkthrough">
      <div className="space-y-1">
        <h2 className="text-xl font-semibold">文件辨識（6 號）</h2>
        <p className="text-sm text-gray-600">
          選一份文件，用 6 號真正的程式辨識，每按一次「下一步」看一個步驟。展示用的事件是「日本
          2026-07-05～07-10，班機延誤」；Google Drive
          是假的，檔案不會存到任何地方；畫面上的文字都已經遮過個資。
        </p>
      </div>

      {error && (
        <p role="alert" className="rounded-md bg-red-50 p-2 text-red-800" data-testid="error">
          {error}
        </p>
      )}

      <div className={box}>
        <h3 className="font-semibold">1. 選文件</h3>
        <div className="flex flex-wrap gap-2" data-testid="samples">
          {samples.map((s) => (
            <Button
              key={s.name}
              type="button"
              disabled={busy}
              className={secondary}
              onClick={() => void pickSample(s)}
            >
              {s.label}
            </Button>
          ))}
        </div>
        <form onSubmit={uploadAction} className="flex flex-wrap items-center gap-2">
          <input
            type="file"
            name="file"
            accept=".pdf,.jpg,.jpeg,.png"
            aria-label="上傳自己的文件"
            data-testid="file"
          />
          <Button type="submit" disabled={busy} className={primary} data-testid="upload">
            用這份文件辨識
          </Button>
        </form>
        <div className="flex flex-wrap gap-4 text-sm">
          <label className="flex items-center gap-1">
            <input
              type="checkbox"
              checked={hasGrant}
              onChange={(e) => setHasGrant(e.target.checked)}
            />
            使用者已授權 Google Drive
          </label>
          <label className="flex items-center gap-1">
            <input
              type="checkbox"
              checked={draftRules}
              onChange={(e) => setDraftRules(e.target.checked)}
            />
            套用合格規範草稿（假設已確認）
          </label>
        </div>
        <p className="text-xs text-gray-500">
          照片要在 .env 設定 Azure 才讀得到；沒設定時會停在第一步。範例文件都是虛構的電子 PDF。
        </p>
      </div>

      {result && (
        <div className={box} data-testid="steps">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="font-semibold">2. 一步一步看：{fileLabel}</h3>
            <div className="flex gap-2">
              <Button
                type="button"
                className={primary}
                disabled={allShown}
                onClick={() => setShown((n) => n + 1)}
                data-testid="next"
              >
                下一步（{Math.min(shown, steps.length)}／{steps.length}）
              </Button>
              <Button
                type="button"
                className={secondary}
                disabled={allShown}
                onClick={() => setShown(steps.length)}
              >
                全部顯示
              </Button>
            </div>
          </div>
          <ol className="space-y-2">
            {steps.slice(0, shown).map((step, i) => {
              const style = STATE_STYLE[step.state];
              return (
                <li
                  key={step.key}
                  className={`rounded-md border p-2 ${style.className}`}
                  data-testid={`step-${step.key}`}
                >
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="font-semibold">
                      {i + 1}. {step.title}
                    </span>
                    <span className="text-xs">{style.label}</span>
                  </div>
                  <p className="text-sm">{step.summary}</p>
                  {step.detail && (
                    <pre className="mt-1 overflow-x-auto whitespace-pre-wrap rounded bg-white/70 p-2 text-xs">
                      {step.detail}
                    </pre>
                  )}
                </li>
              );
            })}
          </ol>
          {allShown && (
            <div
              className={`space-y-1 rounded-md border-2 p-3 ${RESULT_STYLE[result.status]}`}
              data-testid="result"
            >
              <p className="text-lg font-bold">結果：{result.status_label}</p>
              <dl className="grid grid-cols-[7em_1fr] gap-x-2 gap-y-1 text-sm">
                <dt className="text-gray-600">文件種類</dt>
                <dd>{result.document_kind ?? "未判定"}</dd>
                <dt className="text-gray-600">對到的待辦</dt>
                <dd>{result.todo_title ?? "—"}</dd>
                <dt className="text-gray-600">待辦</dt>
                <dd>{result.todo_complete ? "已自動勾起來" : "沒有勾"}</dd>
                <dt className="text-gray-600">給使用者的提醒</dt>
                <dd>{result.reason ?? "—"}</dd>
                <dt className="text-gray-600">存檔位置</dt>
                <dd className="break-all">{result.saved_path ?? "沒有存檔"}</dd>
              </dl>
            </div>
          )}
        </div>
      )}

      <div className={box}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="font-semibold">這次展示已通過的文件</h3>
          <Button
            type="button"
            className={secondary}
            disabled={passed.length === 0}
            onClick={() => setPassed([])}
          >
            清空
          </Button>
        </div>
        {passed.length ? (
          <ul className="list-inside list-disc text-sm" data-testid="passed">
            {passed.map((kind) => (
              <li key={kind}>{kind}</li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-gray-500">
            還沒有。試試先傳「登機證」，再傳「電子機票」：第一份待辦還沒完成，兩份都到才會勾起來。
          </p>
        )}
      </div>
    </section>
  );
}
