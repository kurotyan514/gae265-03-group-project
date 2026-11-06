import { useQuery } from "@tanstack/react-query";
import { listInsurancesOptions } from "../../client/@tanstack/react-query.gen";

/** 險種清單：條數、待處理條文數、最近一次檢索自檢。有問題的險種排前面，一眼看得到要處理哪個。 */
export function InsuranceStatus() {
  const insurances = useQuery({ ...listInsurancesOptions(), refetchInterval: 10_000 });
  const rows = [...(insurances.data ?? [])].sort(
    (a, b) =>
      Number(b.retrieval_check?.abnormal ?? false) - Number(a.retrieval_check?.abnormal ?? false) ||
      (b.pending_count ?? 0) - (a.pending_count ?? 0) ||
      a.code.localeCompare(b.code),
  );
  const pendingTotal = rows.reduce((sum, i) => sum + (i.pending_count ?? 0), 0);
  const abnormalTotal = rows.filter((i) => i.retrieval_check?.abnormal).length;

  return (
    <details className="rounded-md border p-3" data-testid="insurance-status">
      <summary className="cursor-pointer font-medium">
        險種狀態
        <span className="ml-2 text-sm font-normal text-gray-600">
          共 {rows.length} 個險種 · 待處理條文 {pendingTotal} 條 · 檢索品質異常 {abnormalTotal} 個
        </span>
      </summary>
      {insurances.isError && (
        <p role="alert" className="mt-2 text-red-700">
          讀不到險種清單
        </p>
      )}
      <div className="mt-2 max-h-80 overflow-auto">
        <table className="w-full text-left text-sm">
          <thead className="text-gray-600">
            <tr>
              <th className="pr-3 font-medium">代碼</th>
              <th className="pr-3 font-medium">名稱</th>
              <th className="pr-3 font-medium">條數</th>
              <th className="pr-3 font-medium">待處理條文</th>
              <th className="font-medium">檢索自檢</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((i) => (
              <tr key={i.code} data-testid={`insurance-${i.code}`}>
                <td className="pr-3 font-mono">{i.code}</td>
                <td className="pr-3">{i.name}</td>
                <td className="pr-3">{i.rule_count}</td>
                <td className="pr-3">
                  {(i.pending_count ?? 0) > 0 ? (
                    <span className="rounded bg-amber-100 px-1.5 py-0.5 text-amber-900">
                      {i.pending_count} 條
                    </span>
                  ) : (
                    "—"
                  )}
                </td>
                <td>
                  {i.retrieval_check ? (
                    <span
                      className={
                        i.retrieval_check.abnormal
                          ? "rounded bg-red-100 px-1.5 py-0.5 text-red-900"
                          : undefined
                      }
                      title={`前 ${i.retrieval_check.top_n} 名找得到自己；門檻 ${Math.round(i.retrieval_check.threshold * 100)}%`}
                    >
                      {i.retrieval_check.abnormal ? "檢索品質異常 " : ""}
                      {i.retrieval_check.passed}/{i.retrieval_check.checked}（
                      {Math.round(i.retrieval_check.rate * 100)}%）
                      {i.retrieval_check.failed.length > 0 &&
                        ` · 找不到：${i.retrieval_check.failed.join("、")}`}
                    </span>
                  ) : (
                    <span className="text-gray-500">未做</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}
