import type { ReactNode } from "react";
import { TermButton } from "../../components/ui/TermButton";

export type CompareColumn = { label: string; head: ReactNode };
export type CompareRow = {
  key: string;
  label: string;
  /** 你在意的順序（1 起算）；不是你在意的列不給。 */
  concernOrder?: number;
  onTerm: () => void;
  cells: [ReactNode, ReactNode];
};

/**
 * 保障比較表（DESIGN.md 6.15）：桌機三欄（項目｜推薦｜次推薦），推薦欄整欄品牌色框；
 * 你在意的列 leaf-soft 底加「你在意 N」。手機：列名獨佔一列，下面推薦、次推薦兩欄並排。
 * 格子內容由呼叫端決定（保障項目文字照後端給的）。
 */
export function ComparisonTable({
  columns,
  rows,
}: {
  columns: [CompareColumn, CompareColumn];
  rows: CompareRow[];
}) {
  const frame = "border-brand max-md:rounded-btn max-md:border-2 md:border-x-2";
  return (
    <table className="w-full border-separate border-spacing-0 text-left max-md:block">
      <thead className="max-md:hidden">
        <tr>
          <th className="p-3" />
          {columns.map((c, i) => (
            <th
              key={c.label}
              scope="col"
              className={`p-3 align-bottom t-label text-heading ${i === 0 ? `${frame} rounded-t-chip border-t-2` : ""}`}
            >
              {c.head}
            </th>
          ))}
        </tr>
      </thead>
      <tbody className="max-md:block">
        {rows.map((row, r) => {
          const last = r === rows.length - 1;
          return (
            <tr
              key={row.key}
              className={`align-top max-md:grid max-md:grid-cols-2 max-md:gap-2 max-md:border-b max-md:border-line max-md:px-1 max-md:py-3 ${
                row.concernOrder ? "bg-leaf-soft" : ""
              }`}
            >
              <th
                scope="row"
                className="border-t border-line p-3 font-normal max-md:col-span-2 max-md:border-t-0 max-md:p-0"
              >
                <div className="flex flex-col items-start gap-1 max-md:flex-row max-md:items-center max-md:justify-between">
                  <TermButton onClick={row.onTerm}>{row.label}</TermButton>
                  {row.concernOrder && (
                    <span className="t-micro text-leaf-text">你在意 {row.concernOrder}</span>
                  )}
                </div>
              </th>
              {row.cells.map((cell, i) => (
                <td
                  key={columns[i]?.label}
                  className={`border-t border-line p-3 t-body text-ink max-md:border-t-0 max-md:p-3 ${
                    i === 0
                      ? `${frame} ${last ? "md:rounded-b-chip md:border-b-2" : ""} ${r === 0 ? "md:border-t-0" : ""}`
                      : "max-md:rounded-btn max-md:border max-md:border-line max-md:bg-white"
                  }`}
                >
                  <span className="mb-1 block t-micro text-muted md:hidden">
                    {columns[i]?.label}
                  </span>
                  {cell}
                </td>
              ))}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
