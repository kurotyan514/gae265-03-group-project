/** 載入遮罩（DESIGN.md 6.31）：整頁半透明、轉圈與說明文字，`role="status"`。 */
export function LoadingOverlay({ children }: { children: string }) {
  return (
    <div
      role="status"
      className="fixed inset-0 z-50 flex flex-col items-center justify-center gap-4 bg-veil"
    >
      <span
        aria-hidden="true"
        className="size-12 animate-spin rounded-full border-4 border-leaf-soft border-t-leaf motion-reduce:animate-none"
      />
      <p className="m-0 t-label-lg text-heading">{children}</p>
    </div>
  );
}
