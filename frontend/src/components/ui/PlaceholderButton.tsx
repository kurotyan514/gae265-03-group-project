import type { ReactNode } from "react";
import { btn, btnSm, lnk } from "./buttons";
import { useToast } from "./Toast";

/** 沒有功能時 Toast 顯示的文字。 */
export const NOT_AVAILABLE = "暫無作用";

/**
 * 反灰按鈕：畫板有、但後端還沒有對應功能的按鈕（有新狀況、下載全部文件、到 Gmail 查看、
 * 看提醒信範本、刪除檔案）。看起來是灰的，點了跳 Toast「暫無作用」。
 *
 * 用 `aria-disabled="true"`，不用 `disabled`：`disabled` 的按鈕不會觸發點擊，就彈不出 Toast；
 * 鍵盤仍可聚焦，螢幕閱讀器會讀成「已停用」。哪個功能做出來，就把這個元件換成真的按鈕。
 */
export function PlaceholderButton({
  children,
  kind = "button",
  ...rest
}: {
  children: ReactNode;
  /** button：預設按鈕；small：小按鈕；link：文字連結；danger-link：刪除這類紅字連結。 */
  kind?: "button" | "small" | "link" | "danger-link";
  "data-testid"?: string;
}) {
  const toast = useToast();
  const style =
    kind === "link"
      ? lnk
      : kind === "danger-link"
        ? "inline-flex items-center border-0 bg-transparent p-0 t-caption-bold text-danger"
        : kind === "small"
          ? btnSm
          : btn;
  return (
    <button
      type="button"
      aria-disabled="true"
      onClick={() => toast.show(NOT_AVAILABLE)}
      className={`${style} cursor-not-allowed opacity-40 hover:no-underline ${
        kind === "button" || kind === "small" ? "hover:border-line" : ""
      }`}
      {...rest}
    >
      {children}
    </button>
  );
}
