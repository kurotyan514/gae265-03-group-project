import { type ReactNode, useEffect, useState } from "react";
import { type FilePreview, PreviewMeta, PreviewThumb } from "./UploadPreview";
import {
  type ProcessingRow,
  rowBadge,
  SLOW_AFTER_MS,
  SLOW_TEXT,
  STAGE_NAMES,
} from "./uploadRecognition";

/** 單份理賠文件的處理列：檔名＋標籤，下面接內容；流程由 UploadBox 管理。 */
export function UploadProcessingRow({
  row,
  preview,
  onZoom,
  children,
}: {
  row: ProcessingRow;
  /** 這一次上傳時在瀏覽器產生的預覽；重新整理後沒有 */
  preview?: FilePreview;
  onZoom?: () => void;
  children?: ReactNode;
}) {
  const badge = rowBadge(row);
  return (
    <li
      className="flex gap-3 rounded-xl border border-line bg-white px-3.5 py-2.5 t-caption"
      data-testid="upload-row"
    >
      {preview && <PreviewThumb name={row.name} preview={preview} onZoom={() => onZoom?.()} />}
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <span className="flex flex-wrap items-center gap-x-2.5 gap-y-1 font-bold text-ink">
          <span className="[overflow-wrap:anywhere]">{preview ? row.name : `📄 ${row.name}`}</span>
          <span
            className={`ml-auto rounded-xl px-2.5 py-0.5 text-[13px] leading-5 font-bold ${
              badge.tone === "ok"
                ? "bg-leaf-soft text-brand"
                : badge.tone === "warn"
                  ? "bg-warn-soft text-warn-ink"
                  : badge.tone === "bad"
                    ? "bg-danger-soft text-danger-ink"
                    : "bg-paper text-muted"
            }`}
            data-testid="upload-result"
          >
            {badge.text}
          </span>
        </span>
        {preview && <PreviewMeta preview={preview} />}
        {children}
      </div>
    </li>
  );
}

/**
 * 處理中：讀取內容 → 對應待辦 → 檢查規則，逐步亮起（設計者 11/13）。已亮過的打勾，目前這一步轉圈，還沒到的是空圈。
 * 超過 SLOW_AFTER_MS 追加安撫。系統設定「減少動態」時不轉圈，目前這一步改成實心圓點。
 * 階段是示意，結果出來後整列換成標籤，不留階段、也不寫失敗停在哪一步。
 */
export function WorkingNote({ stage = 0 }: { stage?: number }) {
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    const timer = setTimeout(() => setSlow(true), SLOW_AFTER_MS);
    return () => clearTimeout(timer);
  }, []);
  return (
    <span className="flex flex-col gap-1" data-testid="upload-working">
      <ol
        className="m-0 flex list-none flex-wrap items-center gap-x-2 gap-y-1 p-0 text-[13px] leading-5"
        data-testid="upload-stages"
      >
        {STAGE_NAMES.map((name, i) => {
          const state = i < stage ? "done" : i === stage ? "run" : "wait";
          return (
            <li
              key={name}
              className={`inline-flex items-center gap-1.5 ${
                state === "wait" ? "text-muted" : "font-bold text-heading"
              }`}
              data-testid="upload-stage"
              data-state={state}
              aria-current={state === "run" ? "step" : undefined}
            >
              {i > 0 && (
                <span className="text-muted" aria-hidden="true">
                  →
                </span>
              )}
              {state === "run" ? (
                <i
                  className="size-4 shrink-0 animate-spin rounded-full border-[1.5px] border-leaf border-t-transparent motion-reduce:animate-none motion-reduce:border-t-leaf motion-reduce:bg-leaf"
                  aria-hidden="true"
                  data-testid="upload-spinner"
                />
              ) : (
                <i
                  className={`inline-grid size-4 shrink-0 place-items-center rounded-full border-[1.5px] text-[10px] not-italic ${
                    state === "done" ? "border-leaf bg-leaf text-white" : "border-line bg-paper"
                  }`}
                  aria-hidden="true"
                >
                  {state === "done" ? "✓" : ""}
                </i>
              )}
              {name}
              <span className="sr-only">
                ：{state === "done" ? "完成" : state === "run" ? "進行中" : "尚未開始"}
              </span>
            </li>
          );
        })}
      </ol>
      {slow && (
        <span className="text-[13px] leading-5 text-muted" data-testid="upload-slow">
          {SLOW_TEXT}
        </span>
      )}
    </span>
  );
}

/** 備註與錯誤文字的色調：不合格紅、需要你確認琥珀（只有這兩種色調需要停下來的說明） */
export const STOP = {
  bad: { text: "text-danger-ink" },
  warn: { text: "text-warn-ink" },
};
