import type { ChangeEvent, ReactNode } from "react";
import { btnSm } from "./buttons";

/**
 * 檔案拖放區（DESIGN.md 6.10）：2px 虛線框、圓角 16、米白底；標題、說明，下面放按鈕
 * （`FilePickButton` 或授權按鈕）與已選檔案。
 */
export function FileDrop({
  title,
  description,
  children,
}: {
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-2.5 rounded-tile border-2 border-dashed border-line bg-paper px-6 py-5.5">
      <b className="t-label-lg text-heading">{title}</b>
      {description && <p className="m-0 t-caption text-muted">{description}</p>}
      {children}
    </div>
  );
}

/** 「選擇檔案」按鈕：透明的 file input 疊在按鈕上，所以 `setInputFiles` 這類測試可以直接對 input。 */
export function FilePickButton({
  label,
  accept,
  multiple,
  disabled,
  onFiles,
  inputTestId,
}: {
  label: ReactNode;
  accept?: string;
  multiple?: boolean;
  disabled?: boolean;
  onFiles: (files: File[]) => void;
  inputTestId?: string;
}) {
  function change(e: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []);
    if (files.length) onFiles(files);
    e.target.value = ""; // 同一個檔案可以再選一次
  }
  return (
    <span
      className={`${btnSm} relative self-start overflow-hidden ${
        disabled ? "cursor-not-allowed opacity-40" : ""
      }`}
    >
      {label}
      <input
        type="file"
        accept={accept}
        multiple={multiple}
        disabled={disabled}
        onChange={change}
        data-testid={inputTestId}
        className="absolute inset-0 cursor-pointer opacity-0 disabled:cursor-not-allowed"
      />
    </span>
  );
}

/** 已選檔案：`📎 檔名 · 已讀取`，檔名過長會換行。 */
export function PickedFile({ name, status = "已讀取" }: { name: string; status?: string }) {
  return (
    <p className="m-0 [overflow-wrap:anywhere] t-caption-bold text-brand">
      📎 {name} · {status}
    </p>
  );
}
