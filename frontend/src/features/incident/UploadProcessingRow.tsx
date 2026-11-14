import { type ReactNode, useEffect, useState } from "react";
import { type FilePreview, PreviewMeta, PreviewThumb } from "./UploadPreview";
import {
  type ProcessingRow,
  rowBadge,
  SLOW_AFTER_MS,
  SLOW_TEXT,
  STEP_NAMES,
  type StepState,
  type Steps,
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

const STEP_ICON: Record<StepState, string> = { wait: "", run: "", ok: "✓", bad: "✗" };

/**
 * 處理中：逐份顯示「讀取內容 → 對應待辦 → 檢查規則」（1113 討論、ADR-0028），正在做的那一步轉圈；
 * 超過 SLOW_AFTER_MS 追加安撫。系統設定「減少動態」時不轉圈。有結果後這一行收起，只留結果。
 */
export function StepNote({ steps }: { steps: Steps }) {
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    const timer = setTimeout(() => setSlow(true), SLOW_AFTER_MS);
    return () => clearTimeout(timer);
  }, []);
  return (
    <span className="flex flex-col gap-1" data-testid="upload-working">
      <span
        className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] text-muted"
        data-testid="upload-steps"
      >
        {STEP_NAMES.map((name, i) => (
          <span key={name} className="contents">
            {i > 0 && (
              <span className="text-line" aria-hidden="true">
                →
              </span>
            )}
            <span
              className={`inline-flex items-center gap-1.5 whitespace-nowrap ${
                steps[i] === "run" ? "font-bold text-heading" : ""
              }`}
              data-testid="upload-step"
              data-state={steps[i]}
            >
              <i
                aria-hidden="true"
                className={`inline-grid size-[18px] place-items-center rounded-full border-[1.5px] text-[11px] not-italic ${
                  steps[i] === "run"
                    ? "animate-spin border-leaf border-t-transparent motion-reduce:animate-none"
                    : steps[i] === "ok"
                      ? "border-leaf bg-leaf text-white"
                      : steps[i] === "bad"
                        ? "border-coral bg-coral text-white"
                        : "border-line bg-paper"
                }`}
              >
                {STEP_ICON[steps[i] ?? "wait"]}
              </i>
              {name}
            </span>
          </span>
        ))}
      </span>
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
