import type { ReactNode } from "react";
import { type ProcessingRow, recognitionBadge } from "./uploadRecognition";

/** 單份理賠文件的處理列；流程與計時器由 UploadBox 管理。 */
export function UploadProcessingRow({
  row,
  children,
}: {
  row: ProcessingRow;
  children: ReactNode;
}) {
  const badge = recognitionBadge(row);
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
