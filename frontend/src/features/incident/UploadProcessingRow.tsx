import { type ReactNode, useEffect, useState } from "react";
import {
  type ProcessingRow,
  rowBadge,
  SLOW_AFTER_MS,
  SLOW_TEXT,
  type StageResult,
  WORKING_TEXT,
} from "./uploadRecognition";

/** 單份理賠文件的處理列：檔名＋標籤，下面接內容；流程由 UploadBox 管理。 */
export function UploadProcessingRow({
  row,
  children,
}: {
  row: ProcessingRow;
  children?: ReactNode;
}) {
  const badge = rowBadge(row);
  return (
    <li
      className="flex flex-col gap-1.5 rounded-xl border border-line bg-white px-3.5 py-2.5 t-caption"
      data-testid="upload-row"
    >
      <span className="flex flex-wrap items-center gap-x-2.5 gap-y-1 font-bold text-ink">
        <span className="[overflow-wrap:anywhere]">📄 {row.name}</span>
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
      {children}
    </li>
  );
}

/**
 * 處理中：不確定進度，只有一句話；超過 SLOW_AFTER_MS 追加安撫。
 * 系統設定「減少動態」時轉圈由 CSS（motion-reduce）隱藏，只剩文字。
 */
export function WorkingNote() {
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    const timer = setTimeout(() => setSlow(true), SLOW_AFTER_MS);
    return () => clearTimeout(timer);
  }, []);
  return (
    <span className="flex flex-col gap-1" data-testid="upload-working">
      <span className="inline-flex items-center gap-2 text-[13px] leading-5 font-bold text-heading">
        <i
          className="size-4 shrink-0 animate-spin rounded-full border-[1.5px] border-leaf border-t-transparent motion-reduce:hidden"
          aria-hidden="true"
          data-testid="upload-spinner"
        />
        {WORKING_TEXT}
      </span>
      {slow && (
        <span className="text-[13px] leading-5 text-muted" data-testid="upload-slow">
          {SLOW_TEXT}
        </span>
      )}
    </span>
  );
}

const DOT: Record<StageResult["state"], string> = {
  ok: "border-leaf bg-leaf text-white",
  saved: "border-leaf bg-leaf text-white",
  stop: "border-coral bg-coral text-white",
  nosave: "border-coral bg-coral text-white",
  unknown: "border-line bg-paper text-muted",
  skip: "border-line bg-paper text-muted",
};
const MARK: Record<StageResult["state"], string> = {
  ok: "✓",
  saved: "✓",
  stop: "✗",
  nosave: "✗",
  unknown: "",
  skip: "",
};

/** 四個處理階段的緊湊一行：輔助資訊，只有停下或沒有存的那一步是紅色 */
export function StageTrail({ stages }: { stages: StageResult[] }) {
  return (
    <ul
      className="m-0 flex list-none flex-wrap items-center gap-x-2 gap-y-1 p-0 text-[13px] text-muted"
      data-testid="upload-stages"
    >
      {stages.map((s, i) => (
        <li
          key={s.name}
          className="inline-flex items-center gap-1.5"
          data-testid="upload-stage"
          data-state={s.state}
        >
          {i > 0 && (
            <span className="text-line" aria-hidden="true">
              →
            </span>
          )}
          <i
            className={`inline-grid size-[18px] place-items-center rounded-full border-[1.5px] text-[11px] not-italic ${DOT[s.state]}`}
            aria-hidden="true"
          >
            {MARK[s.state]}
          </i>
          <span
            className={s.state === "stop" || s.state === "nosave" ? "text-danger-ink" : undefined}
          >
            {s.name}
            <span className="sr-only">：{s.label}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}
