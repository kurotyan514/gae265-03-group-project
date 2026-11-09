import type { ReactNode } from "react";

/** 情境故事（DESIGN.md 6.17）：sun 色左邊線。 */
export function Story({ children }: { children: ReactNode }) {
  return <p className="m-0 border-l-4 border-sun pl-4 t-body text-ink">{children}</p>;
}

/**
 * 試算卡外框（DESIGN.md 6.18）：chip「模板試算・不經 AI」、粗體結論句，下面放 `MiniTable`
 * 與底部說明（`children`）。
 */
export function SimulationCard({
  conclusion,
  children,
}: {
  conclusion: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="flex flex-col gap-4 rounded-tile border border-line bg-white p-4 md:p-5">
      <span className="w-fit rounded-chip bg-leaf-soft px-3 py-0.5 t-caption-bold text-brand">
        模板試算・不經 AI
      </span>
      <p data-testid="conclusion" className="m-0 t-label-lg text-heading">
        {conclusion}
      </p>
      {children}
    </section>
  );
}

export type MiniColumn = { key: string; label: ReactNode };
export type MiniRow = { key: string; head: ReactNode; cells: ReactNode[] };

/** 試算小表：保障項目｜推薦｜次推薦；第一個方案欄（推薦）整欄品牌色框。窄螢幕可橫向捲動。 */
export function MiniTable({
  headLabel,
  columns,
  rows,
}: {
  headLabel: string;
  columns: MiniColumn[];
  rows: MiniRow[];
}) {
  const frame = "border-x-2 border-brand";
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-separate border-spacing-0 text-left">
        <thead>
          <tr>
            <th scope="col" className="p-2 t-caption-bold text-muted md:p-3">
              {headLabel}
            </th>
            {columns.map((c, i) => (
              <th
                key={c.key}
                scope="col"
                className={`p-2 t-caption-bold text-heading md:p-3 ${i === 0 ? `${frame} rounded-t-chip border-t-2` : ""}`}
              >
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, r) => (
            <tr key={row.key} className="align-top">
              <th scope="row" className="border-t border-line p-2 font-normal md:p-3">
                {row.head}
              </th>
              {row.cells.map((cell, i) => (
                <td
                  // biome-ignore lint/suspicious/noArrayIndexKey: 欄位固定，順序就是 columns
                  key={i}
                  className={`border-t border-line p-2 md:p-3 ${
                    i === 0
                      ? `${frame} ${r === rows.length - 1 ? "rounded-b-chip border-b-2" : ""} ${r === 0 ? "border-t-0" : ""}`
                      : ""
                  }`}
                >
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
