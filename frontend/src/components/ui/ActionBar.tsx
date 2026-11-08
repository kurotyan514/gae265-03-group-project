import type { ReactNode } from "react";

/**
 * 動作列（DESIGN.md 6.1）：可換行，間距 16（手機 12）。返回類按鈕放左邊，
 * 主要動作放最右邊：用 `<ActionBar.Push>` 包起來（`margin-left: auto`）。
 * 手機的 `twoColumns`：兩欄 grid，標了 `<ActionBar.Full>` 的主要按鈕移到最上方並佔滿整列。
 */
export function ActionBar({
  children,
  twoColumns = false,
}: {
  children: ReactNode;
  twoColumns?: boolean;
}) {
  return (
    <div
      className={`flex flex-wrap items-center gap-3 md:gap-4 ${
        twoColumns
          ? "max-md:grid max-md:grid-cols-2 max-md:[&>*]:w-full max-md:[&>*]:justify-center"
          : ""
      }`}
    >
      {children}
    </div>
  );
}

/** 推到動作列最右邊（桌機）；手機的兩欄模式下不推。 */
function Push({ children }: { children: ReactNode }) {
  return (
    <div className="ml-auto flex flex-wrap items-center gap-3 max-md:ml-0 md:gap-4">{children}</div>
  );
}

/** 手機兩欄模式下，移到最上方並佔滿整列（給主要按鈕）。 */
function Full({ children }: { children: ReactNode }) {
  return <div className="max-md:order-first max-md:col-span-full md:contents">{children}</div>;
}

ActionBar.Push = Push;
ActionBar.Full = Full;
