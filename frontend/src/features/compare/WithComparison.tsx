import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { getComparisonOptions } from "../../client/@tanstack/react-query.gen";
import type { ComparisonOut } from "../../client/types.gen";

/** 讀回比較紀錄後才畫 children；讀取中與找不到時顯示對應訊息。1-1、1-2、1-3 共用。 */
export function WithComparison({
  id,
  children,
}: {
  id: string;
  children: (comparison: ComparisonOut) => ReactNode;
}) {
  const comparison = useQuery(getComparisonOptions({ path: { comparison_id: id } }));

  if (comparison.error) {
    return (
      <p role="alert" className="text-red-600">
        找不到這筆比較紀錄。
      </p>
    );
  }
  // 表單只用讀回的值初始化一次：等這次進頁面的讀取完成，不拿快取裡可能過期的資料
  if (!comparison.isFetchedAfterMount || !comparison.data) return <p>讀取中…</p>;
  return children(comparison.data);
}
