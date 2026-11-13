import { useState } from "react";
import { btn } from "../../components/ui/buttons";
import { Dialog, DialogShell } from "../../components/ui/DialogShell";

/**
 * 處理列的預覽（票 #292、ADR-0027）：只存在這一次上傳的畫面。
 * 圖片用 URL.createObjectURL 在瀏覽器產生縮圖，資料不離開瀏覽器；PDF 與 HEIC 是圖示加說明。
 */
export type FilePreview = {
  kind: "image" | "pdf" | "heic" | "other";
  /** 只有圖片有：object URL，要在不用時 revoke */
  url?: string;
  size: string;
};

const extOf = (name: string) => name.split(".").pop()?.toLowerCase() ?? "";

/** 檔案大小的文字：KB 或 MB，一位小數 */
export function formatSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/** 依副檔名與 type 判斷種類（iPhone 的 HEIC 常常 type 是空字串） */
export function previewKind(file: File): FilePreview["kind"] {
  const ext = extOf(file.name);
  const type = file.type.toLowerCase();
  if (ext === "heic" || ext === "heif" || type === "image/heic" || type === "image/heif")
    return "heic";
  if (ext === "pdf" || type === "application/pdf") return "pdf";
  if (["jpg", "jpeg", "png"].includes(ext) || type === "image/jpeg" || type === "image/png")
    return "image";
  return "other";
}

/** 圖片才建立 object URL；呼叫的人負責 revoke */
export function makePreview(file: File): FilePreview {
  const kind = previewKind(file);
  return {
    kind,
    size: formatSize(file.size),
    url: kind === "image" ? URL.createObjectURL(file) : undefined,
  };
}

const BOX =
  "inline-grid size-14 shrink-0 place-items-center rounded-tag border border-line bg-paper";

/** 縮圖按鈕（可點開放大）；圖片載不起來就退回圖示 */
export function PreviewThumb({
  name,
  preview,
  onZoom,
}: {
  name: string;
  preview: FilePreview;
  onZoom: () => void;
}) {
  const [broken, setBroken] = useState(false);
  if (preview.kind === "image" && preview.url && !broken) {
    return (
      <button
        type="button"
        onClick={onZoom}
        aria-label={`放大看 ${name}`}
        className={`${BOX} cursor-zoom-in overflow-hidden focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-leaf`}
        data-testid="upload-thumb"
      >
        <img
          src={preview.url}
          alt=""
          className="size-full object-cover"
          onError={() => setBroken(true)}
        />
      </button>
    );
  }
  const label = preview.kind === "pdf" ? "PDF" : preview.kind === "heic" ? "HEIC" : "檔案";
  return (
    <span
      className={`${BOX} t-micro font-bold text-muted`}
      aria-hidden="true"
      data-testid="upload-icon"
      data-kind={preview.kind}
    >
      {label}
    </span>
  );
}

/** 檔案大小，HEIC 另外說明無法預覽 */
export function PreviewMeta({ preview }: { preview: FilePreview }) {
  return (
    <span className="text-[13px] leading-5 text-muted" data-testid="upload-meta">
      {preview.size}
      {preview.kind === "heic" && (
        <span data-testid="upload-heic-note"> · 無法預覽，但仍會上傳</span>
      )}
    </span>
  );
}

/** 放大的圖：Esc、遮罩與「關閉」都能關；手機上也有按鈕。保留最後的檔名避免關閉動畫時標題閃空。 */
export function ZoomDialog({
  zoom,
  onClose,
}: {
  zoom: { name: string; url: string } | null;
  onClose: () => void;
}) {
  const [last, setLast] = useState({ name: "", url: "" });
  if (zoom && (zoom.name !== last.name || zoom.url !== last.url)) setLast(zoom);
  return (
    <DialogShell
      open={zoom !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={last.name}
      testId="upload-zoom"
      actions={
        <Dialog.Close className={btn} data-testid="upload-zoom-close">
          關閉
        </Dialog.Close>
      }
    >
      <img
        src={last.url}
        alt={`${last.name} 放大`}
        className="max-h-[60vh] w-full rounded-tag object-contain"
      />
    </DialogShell>
  );
}
