import type { ReactNode } from "react";

/**
 * 表單欄位（DESIGN.md 6.6）。輸入框、下拉、textarea 共用 `fieldInput`：最小高 52、圓角 12、
 * focus 時框線變品牌色加光暈（不用預設 outline）、disabled 時灰底。
 * 用法：`<select className={fieldInput}>`；要滿寬時自己加 `w-full`。
 */
export const fieldInput =
  "min-h-[52px] rounded-btn border border-line bg-white px-4 py-3 t-body text-ink focus:border-brand focus:shadow-focus-input focus:outline-none disabled:bg-paper disabled:text-muted";

/** 欄位：標籤（label，heading）加欄位本體，下面可以接說明或提示。欄位內垂直間距 8。 */
export function Field({
  label,
  htmlFor,
  required = false,
  children,
}: {
  label: ReactNode;
  htmlFor?: string;
  /** 必填：標籤後面加「必填」記號（只是提醒，不擋送出，擋不擋由表單自己決定）。 */
  required?: boolean;
  children: ReactNode;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <label htmlFor={htmlFor} className="t-label text-heading">
        {label}
        {required && <RequiredMark />}
      </label>
      {children}
    </div>
  );
}

/** 欄位下方的說明（caption、muted）。 */
export function FieldHint({ children, id }: { children: ReactNode; id?: string }) {
  return (
    <small id={id} className="t-caption text-muted">
      {children}
    </small>
  );
}

/** 成功提示：例如「✓ 由保單自動帶入，可修改」。 */
export function FieldOk({ children, ...rest }: { children: ReactNode; "data-testid"?: string }) {
  return (
    <p className="m-0 t-caption text-brand" {...rest}>
      ✓ {children}
    </p>
  );
}

/** 警示提示：例如「保單上讀不到，請自行選擇」。 */
export function FieldWarn({ children, ...rest }: { children: ReactNode; "data-testid"?: string }) {
  return (
    <p className="m-0 t-caption text-warn" {...rest}>
      {children}
    </p>
  );
}

/** 錯誤訊息：`role="alert"`，沒有內容時不顯示。 */
export function FieldError({
  children,
  ...rest
}: {
  children?: ReactNode;
  "data-testid"?: string;
}) {
  if (!children) return null;
  return (
    <p role="alert" className="m-0 t-caption-bold text-danger" {...rest}>
      {children}
    </p>
  );
}

/** 「必填」記號：小字、危險色，放在欄位標籤後面。 */
export function RequiredMark() {
  return <span className="ml-1.5 t-caption-bold text-danger">必填</span>;
}
