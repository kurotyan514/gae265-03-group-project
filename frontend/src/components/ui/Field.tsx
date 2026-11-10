import type { ReactNode } from "react";

/**
 * 表單欄位（DESIGN.md 6.6）。輸入框、下拉、textarea 共用 `fieldInput`：最小高 52、圓角 12、
 * focus 時框線變品牌色加光暈（不用預設 outline）、disabled 時灰底。
 * 用法：`<select className={fieldInput}>`；要滿寬時自己加 `w-full`。
 */
export const fieldInput =
  "min-h-[52px] rounded-btn border border-line bg-white px-4 py-3 t-body text-ink focus:border-brand focus:shadow-focus-input focus:outline-none disabled:bg-paper disabled:text-muted";

/**
 * 下拉選單：瀏覽器預設的箭頭貼著右邊框，改用自己的箭頭，離邊框 16px，右側留空間不讓文字壓到箭頭
 * （同 PlanCard 保額下拉的做法）。用法：`<select className={`${fieldSelect} w-full`}>`。
 */
export const fieldSelect = `${fieldInput} appearance-none bg-[url('data:image/svg+xml,%3Csvg%20xmlns=%22http://www.w3.org/2000/svg%22%20viewBox=%220%200%2024%2024%22%20fill=%22none%22%20stroke=%22%23285442%22%20stroke-width=%222.6%22%20stroke-linecap=%22round%22%20stroke-linejoin=%22round%22%3E%3Cpath%20d=%22m6%209%206%206%206-6%22/%3E%3C/svg%3E')] bg-[length:1rem] bg-[right_1rem_center] bg-no-repeat pr-11`;

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
