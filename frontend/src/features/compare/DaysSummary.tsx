import type { ReactNode } from "react";

/** 天數提示（DESIGN.md 6.7）：leaf-soft 色塊，內容變了讀屏會唸（`aria-live="polite"`）。 */
export function DaysSummary({ children }: { children: ReactNode }) {
  return (
    <p
      data-testid="trip-days"
      aria-live="polite"
      className="m-0 rounded-btn bg-leaf-soft px-4 py-3 t-label text-heading"
    >
      {children}
    </p>
  );
}
