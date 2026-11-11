import type { ReactNode } from "react";

/**
 * 分段選擇器（DESIGN.md 6.9）：外框 1px、圓角 12、白底、自身寬度；每段高 46。
 * 選中的那段是 leaf-soft 底加 inset 2px 品牌色框。用 `aria-pressed` 表示選取狀態。
 */
export function Segmented<T extends string>({
  value,
  onChange,
  options,
  label,
}: {
  value: T;
  onChange: (value: T) => void;
  options: { value: T; label: ReactNode; testId?: string }[];
  /** 給螢幕閱讀器的群組名稱。 */
  label: string;
}) {
  return (
    <fieldset
      aria-label={label}
      className="m-0 inline-flex min-w-0 self-start overflow-hidden rounded-btn border border-line bg-white p-0"
    >
      {options.map((o, i) => {
        const on = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            aria-pressed={on}
            data-testid={o.testId}
            onClick={() => onChange(o.value)}
            className={`min-h-[46px] px-6 t-label focus-visible:outline-3 focus-visible:-outline-offset-2 focus-visible:outline-leaf ${
              i > 0 ? "border-l border-line" : ""
            } ${on ? "rounded-[11px] bg-leaf-soft text-heading shadow-[inset_0_0_0_2px_var(--color-brand)]" : "text-muted"}`}
          >
            {o.label}
          </button>
        );
      })}
    </fieldset>
  );
}
