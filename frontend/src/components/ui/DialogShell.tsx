import { Dialog } from "@base-ui/react/dialog";
import type { ReactNode } from "react";

/**
 * 對話框殼（DESIGN.md 6.30）：遮罩、白底卡、標題、內容、靠右的按鈕列。
 * 開啟時焦點移到第一個可聚焦的元素（Base UI 處理），遮罩點一下關閉。
 * `variant="bottom"`：底部抽屜，只有上方圓角。`variant="wide"`：置中、最寬 720px（列表型視窗，例如「從過去的比較帶入」）。
 */
export function DialogShell({
  open,
  onOpenChange,
  title,
  description,
  children,
  actions,
  variant = "center",
  testId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  /** 按鈕列（靠右），通常是 `<Dialog.Close>` 或自己的按鈕。 */
  actions?: ReactNode;
  variant?: "center" | "wide" | "bottom";
  testId?: string;
}) {
  const centered =
    "top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 rounded-2xl md:rounded-panel";
  const position =
    variant === "bottom"
      ? "bottom-0 left-1/2 w-full max-w-[720px] -translate-x-1/2 rounded-t-panel"
      : variant === "wide"
        ? `${centered} w-[min(45rem,calc(100vw-2rem))]`
        : `${centered} w-[min(30rem,calc(100vw-2rem))]`;
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Backdrop className="fixed inset-0 z-40 bg-scrim" />
        <Dialog.Popup
          data-testid={testId}
          className={`fixed z-40 flex max-h-[90vh] flex-col gap-3.5 overflow-auto bg-white p-5.5 shadow-dialog md:p-7 ${position}`}
        >
          <Dialog.Title className="m-0 t-dialog-title text-heading">{title}</Dialog.Title>
          {description && (
            <Dialog.Description render={<div />} className="space-y-2 t-body text-ink">
              {description}
            </Dialog.Description>
          )}
          {children}
          {actions && <div className="flex flex-wrap justify-end gap-3">{actions}</div>}
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/** 選項列：滿寬、1px 框、圓角 14，左文字右 ›；hover 框線變品牌色。 */
export function PickRow({
  children,
  onClick,
  ...rest
}: {
  children: ReactNode;
  onClick: () => void;
  "data-testid"?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center justify-between gap-3 rounded-chip border border-line bg-white px-4.5 py-3.5 text-left hover:border-brand focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-leaf"
      {...rest}
    >
      <span>{children}</span>
      <span aria-hidden="true" className="text-leaf-text">
        ›
      </span>
    </button>
  );
}

export { Dialog };
