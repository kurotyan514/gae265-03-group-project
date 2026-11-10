import { useEffect, useState } from "react";
import type { DocumentOut, DocumentView, IncidentContext } from "../../client/types.gen";
import { btnPri } from "../../components/ui/buttons";
import { FileDrop, FilePickButton } from "../../components/ui/FileDrop";
import { GoogleConsentDialog } from "../google/GoogleConsentDialog";
import { useGoogleGrant } from "../google/useGoogleGrant";
import { errorText, useIncident } from "./shared";

type Status = DocumentView["recognition_status"];

const STATUS: Record<Status, string> = {
  pending: "等待辨識",
  recognized: "辨識通過",
  needs_review: "無法辨識，需要你確認",
  incomplete: "內容不完整",
  failed: "辨識失敗",
};

const STEPS = ["讀取內容", "對應待辦", "檢查規則"] as const;

const HELP =
  "可一次選多份，手機可直接拍照；PDF、JPG、PNG，每份 10 MB 內。上傳後依「事故類型_待辦名稱_序號」重新命名，存在你自己的 Google Drive。";

/** 上傳回應的訊息條（DESIGN.md 6.26）：有問題的用警示或危險底，通過的用一般文字。 */
function UploadNote({ status, children }: { status: string; children: string }) {
  const style =
    status === "recognized" || status === "pending"
      ? "text-brand"
      : status === "failed"
        ? "bg-danger-soft text-danger-ink"
        : "bg-warn-soft text-warn-ink";
  return <p className={`m-0 rounded-tag px-3 py-2 t-caption ${style}`}>{children}</p>;
}

type Result = { status: Status; text: string; ticked: boolean; appended: boolean };

/** 「這次上傳 N 份：…」：數量為 0 的類別不列。 */
export function summarize(results: Pick<Result, "status" | "ticked" | "appended">[]): string {
  const count = (pick: (r: (typeof results)[number]) => boolean) => results.filter(pick).length;
  const parts: [number, string][] = [
    [count((r) => r.ticked), "已自動打勾"],
    [count((r) => r.appended), "追加到已完成的待辦"],
    [count((r) => r.status === "incomplete"), "不合格"],
    [count((r) => r.status === "needs_review"), "無法辨識"],
    [count((r) => r.status === "failed"), "辨識失敗"],
  ];
  const shown = parts.filter(([n]) => n > 0).map(([n, label]) => `${n} 份${label}`);
  return `這次上傳 ${results.length} 份${shown.length ? `：${shown.join("、")}` : ""}`;
}

/**
 * 上傳理賠文件的唯一入口（2-3 理賠頁與 2-4 共用）：選好檔案就逐份上傳辨識，
 * 顯示處理進度與「這次上傳 N 份」摘要。文件存到使用者的 Google Drive，所以 Google 登入的使用者要先授權。
 * 後端一份檔案只有一個請求，「讀取內容 → 對應待辦 → 檢查規則」是這個請求在做的事，步驟高亮只是示意。
 */
export function DocumentUploader({
  id,
  ctx,
  googleUser,
  /** 授權 Google 後要回到的頁面。 */
  next,
  onError,
}: {
  id: string;
  ctx: IncidentContext;
  googleUser: boolean;
  next: string;
  onError: (message: string | null) => void;
}) {
  const { setIncident } = useIncident(id);
  const grant = useGoogleGrant(googleUser);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<{ name: string; index: number; total: number } | null>(
    null,
  );
  const [step, setStep] = useState(0);
  const [results, setResults] = useState<Result[]>([]);
  const [expanded, setExpanded] = useState(false);
  const [help, setHelp] = useState(false);

  const closed = ctx.status === "completed";
  const driveReady = !googleUser || grant.data?.drive === true;

  // 處理中每秒換一個步驟，檔案換了就從頭
  // biome-ignore lint/correctness/useExhaustiveDependencies: progress.index 變了才重新計時
  useEffect(() => {
    setStep(0);
    if (!busy) return;
    const timer = setInterval(() => setStep((s) => Math.min(s + 1, STEPS.length - 1)), 1000);
    return () => clearInterval(timer);
  }, [busy, progress?.index]);

  async function upload(files: File[]) {
    setBusy(true);
    onError(null);
    setResults([]);
    setExpanded(false);
    // 上傳前已完成的待辦：通過的文件對到它，算「追加」，不是「自動打勾」
    const doneBefore = new Set((ctx.todos ?? []).filter((t) => t.is_done).map((t) => t.id));
    const collected: Result[] = [];
    try {
      for (const [index, file] of files.entries()) {
        setProgress({ name: file.name, index, total: files.length });
        const body = new FormData();
        body.append("file", file);
        const response = await fetch(`/api/v1/incidents/${id}/documents`, { method: "POST", body });
        const data = await response.json().catch(() => null);
        if (!response.ok) {
          onError(errorText(data, response.status));
          break;
        }
        const doc = data as DocumentOut;
        const status = doc.recognition_status as Status;
        const matched = status === "recognized" && !!doc.todo_id;
        collected.push({
          status,
          ticked: matched && !doneBefore.has(doc.todo_id ?? ""),
          appended: matched && doneBefore.has(doc.todo_id ?? ""),
          text: `${doc.file_name}：${STATUS[status] ?? status}${doc.reason ? `（${doc.reason}）` : ""}`,
        });
      }
      setResults(collected);
      // 重新讀事件：6 號可能勾選了待辦
      const fresh = await fetch(`/api/v1/incidents/${id}`);
      if (fresh.ok) setIncident(await fresh.json());
    } catch {
      onError(errorText(undefined));
    } finally {
      setProgress(null);
      setBusy(false);
    }
  }

  return (
    <div id="upload-box" className="scroll-mt-24">
      <GoogleConsentDialog
        purpose={consent ? "drive" : null}
        next={next}
        onClose={() => setConsent(false)}
      />
      <FileDrop
        title={
          <span className="flex items-center gap-2">
            上傳理賠文件
            <button
              type="button"
              aria-label="上傳說明"
              aria-expanded={help}
              onClick={() => setHelp(!help)}
              className="grid size-5 place-items-center rounded-full border border-line bg-white p-0 t-caption-bold text-muted"
              data-testid="upload-help-toggle"
            >
              ?
            </button>
          </span>
        }
        description={help ? HELP : undefined}
      >
        {googleUser && grant.data && !grant.data.drive ? (
          // Drive 還不能用：先說明用途再授權（授權會整頁跳走，選好的檔案會不見）
          <button
            type="button"
            className={`${btnPri} self-start`}
            disabled={closed}
            onClick={() => setConsent(true)}
            data-testid="authorize-drive"
          >
            授權 Google Drive 後上傳
          </button>
        ) : (
          <FilePickButton
            label={
              busy
                ? "上傳並辨識中…"
                : googleUser && !grant.data
                  ? "確認 Google 授權中…"
                  : "選擇檔案"
            }
            accept=".pdf,.jpg,.jpeg,.png"
            multiple
            disabled={closed || busy || !driveReady}
            onFiles={(files) => void upload(files)}
            inputTestId="doc-file"
          />
        )}
        {progress && (
          <div className="flex flex-col gap-1.5" role="status" data-testid="upload-progress">
            <p className="m-0 t-caption-bold text-heading">
              正在處理 {progress.total} 份　已完成 {progress.index}／{progress.total}
            </p>
            <progress
              className="h-2 w-full"
              max={progress.total}
              value={progress.index}
              aria-label="上傳進度"
            />
            <p className="m-0 [overflow-wrap:anywhere] t-caption text-muted">{progress.name}</p>
            <ol className="m-0 flex list-none gap-3 p-0 t-caption">
              {STEPS.map((label, i) => (
                <li
                  key={label}
                  className={
                    i === step ? "font-bold text-brand" : i < step ? "text-ink" : "text-muted"
                  }
                >
                  {i < step ? "✓ " : ""}
                  {label}
                </li>
              ))}
            </ol>
          </div>
        )}
        {results.length > 0 && (
          <div className="flex flex-col gap-2" role="status">
            <p className="m-0 t-label text-heading" data-testid="upload-summary">
              {summarize(results)}
            </p>
            <button
              type="button"
              aria-expanded={expanded}
              onClick={() => setExpanded(!expanded)}
              className="self-start border-0 bg-transparent p-0 t-caption-bold text-leaf-text hover:underline"
              data-testid="upload-detail-toggle"
            >
              {expanded ? "收合明細" : `看全部 ${results.length} 份明細`}
            </button>
            {expanded && (
              <div className="flex flex-col gap-2" data-testid="notice">
                {results.map((r) => (
                  <UploadNote key={r.text} status={r.status}>
                    {r.text}
                  </UploadNote>
                ))}
              </div>
            )}
          </div>
        )}
      </FileDrop>
    </div>
  );
}
