import { Button } from "@base-ui/react/button";
import { type FormEvent, type ReactNode, useEffect, useRef } from "react";
import { btnPri } from "./buttons";
import { fieldInput } from "./Field";

/**
 * 對話區（DESIGN.md 6.19）：米白底、框線、圓角 16、可捲動；每次渲染後自動捲到最底，
 * `aria-live="polite"`。裡面放 `ChatMessage`（每則是一個 `<li>`）。
 */
export function ChatLog({
  children,
  minHeight,
  ...rest
}: {
  children: ReactNode;
  /** 最小高（px）；2-2 描述事故用 320。 */
  minHeight?: number;
  "data-testid"?: string;
}) {
  const ref = useRef<HTMLOListElement>(null);
  // 沒有依賴：每次渲染都捲到最底，新訊息才看得到
  useEffect(() => {
    const el = ref.current;
    if (el) el.scrollTop = el.scrollHeight;
  });
  return (
    <ol
      ref={ref}
      aria-live="polite"
      style={minHeight ? { minHeight } : undefined}
      className="m-0 flex max-h-[520px] min-h-[180px] list-none flex-col gap-3.5 overflow-y-auto rounded-tile border border-line bg-paper p-3.5 md:p-5"
      {...rest}
    >
      {children}
    </ol>
  );
}

/** 一則訊息：我方（品牌色底、白字）或 AI（白底框；裡面可放結論 Pill、小表格、依據）。 */
/** `from`：me＝旅客、ai＝助理（不叫 role，免得和 ARIA 的 role 搞混）。 */
export function ChatMessage({ from, children }: { from: "me" | "ai"; children: ReactNode }) {
  return from === "me" ? (
    <li className="max-w-[94%] self-end whitespace-pre-line rounded-bubble rounded-br-[4px] bg-brand px-4 py-2.5 text-white md:max-w-[80%]">
      {children}
    </li>
  ) : (
    <li className="flex max-w-[94%] flex-col gap-2 self-start rounded-bubble rounded-bl-[4px] border border-line bg-white px-4 py-3 md:max-w-[90%]">
      {children}
    </li>
  );
}

/** 系統分隔：例如「以下依新的推薦回答」，兩側各一條線。 */
export function ChatDivider({ children }: { children: ReactNode }) {
  return (
    <li className="flex items-center gap-3 self-stretch text-center t-caption-bold text-brand before:h-px before:flex-1 before:bg-line after:h-px after:flex-1 after:bg-line">
      {children}
    </li>
  );
}

/**
 * 提問列（DESIGN.md 6.21）：輸入框、計數、送出（主要按鈕，輸入為空時 disabled）。
 * 手機：輸入框獨佔一行，計數靠左、按鈕靠右。
 */
export function AskBar({
  value,
  onChange,
  onSubmit,
  maxLength,
  placeholder,
  disabled,
  submitLabel = "送出",
  inputName,
  inputTestId,
  submitTestId,
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  maxLength: number;
  placeholder?: string;
  disabled?: boolean;
  submitLabel?: string;
  inputName?: string;
  inputTestId?: string;
  submitTestId?: string;
}) {
  function submit(e: FormEvent) {
    e.preventDefault();
    if (value.trim() && !disabled) onSubmit();
  }
  return (
    <form onSubmit={submit} className="flex flex-wrap items-center gap-3">
      <input
        name={inputName}
        value={value}
        maxLength={maxLength}
        placeholder={placeholder}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        data-testid={inputTestId}
        className={`${fieldInput} basis-full md:min-w-0 md:flex-1 md:basis-0`}
      />
      <span className="mr-auto whitespace-nowrap t-caption text-muted tabular-nums md:mr-0">
        {value.length}/{maxLength}
      </span>
      <Button
        type="submit"
        disabled={disabled || !value.trim()}
        data-testid={submitTestId}
        className={btnPri}
      >
        {submitLabel}
      </Button>
    </form>
  );
}
