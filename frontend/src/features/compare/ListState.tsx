import type { ReactNode } from "react";

/** 列表的讀取中／錯誤／空三段式；文字由呼叫端決定，有資料時顯示 children。 */
export function ListState({
  isPending,
  error,
  isEmpty,
  loadingText = "讀取中…",
  errorText,
  emptyText,
  children,
}: {
  isPending: boolean;
  error: unknown;
  isEmpty: boolean;
  loadingText?: string;
  errorText: string;
  emptyText: string;
  children: ReactNode;
}) {
  if (isPending) return <p className="px-2 py-7 text-muted">{loadingText}</p>;
  if (error)
    return (
      <p role="alert" className="px-2 py-7 text-red-600">
        {errorText}
      </p>
    );
  if (isEmpty) return <p className="px-2 py-7 text-muted">{emptyText}</p>;
  return <>{children}</>;
}
