import { Button } from "@base-ui/react/button";
import { useQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { Fragment, useState } from "react";
import { listAllRulesOptions, listInsurancesOptions } from "../client/@tanstack/react-query.gen";

export const Route = createFileRoute("/dev/rules")({
  component: RulesPage,
});

const PAGE_SIZE = 50;

/** 瀏覽資料庫裡全部條文（含向量狀態），用來核對匯入有沒有漏。 */
function RulesPage() {
  const [code, setCode] = useState("");
  const [text, setText] = useState("");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState<string | null>(null);

  const insurances = useQuery(listInsurancesOptions());
  const rules = useQuery({
    ...listAllRulesOptions({
      query: {
        limit: PAGE_SIZE,
        offset,
        ...(code ? { insurance_code: code } : {}),
        ...(query ? { q: query } : {}),
      },
    }),
    placeholderData: (previous) => previous,
  });

  const total = rules.data?.total ?? 0;
  const noVector = rules.data?.items.filter((r) => r.embedding_models.length === 0).length ?? 0;

  return (
    <section className="space-y-4">
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          setQuery(text.trim());
          setOffset(0);
        }}
      >
        <label className="space-y-1">
          <span className="block font-medium">險種</span>
          <select
            value={code}
            onChange={(e) => {
              setCode(e.target.value);
              setOffset(0);
            }}
            className="rounded-md border px-2 py-1"
            data-testid="insurance-filter"
          >
            <option value="">
              全部（{insurances.data?.reduce((n, i) => n + i.rule_count, 0) ?? "…"} 條）
            </option>
            {insurances.data?.map((i) => (
              <option key={i.code} value={i.code}>
                {i.code} {i.name}（{i.rule_count}）
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-1">
          <span className="block font-medium">標題或內文包含</span>
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            className="rounded-md border px-2 py-1"
            placeholder="例如：滑雪"
          />
        </label>
        <Button type="submit" className="rounded-md border px-3 py-1 hover:bg-gray-100">
          篩選
        </Button>
      </form>

      {rules.error && (
        <p role="alert" className="text-red-600">
          無法讀取條文：
          {rules.error instanceof Error ? rules.error.message : JSON.stringify(rules.error)}
        </p>
      )}
      {rules.isPending && !rules.error && <p>讀取中…</p>}

      {rules.data && (
        <>
          <p data-testid="total">
            共 {total} 筆，目前第 {total === 0 ? 0 : offset + 1}–
            {Math.min(offset + PAGE_SIZE, total)} 筆
            {noVector > 0 && (
              <span className="ml-2 text-red-600">（這一頁有 {noVector} 條沒有向量）</span>
            )}
          </p>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left text-sm">
              <thead>
                <tr className="border-b">
                  <th className="p-1">險種</th>
                  <th className="p-1">條</th>
                  <th className="p-1">標題</th>
                  <th className="p-1">章</th>
                  <th className="p-1">頁</th>
                  <th className="p-1">向量</th>
                </tr>
              </thead>
              <tbody>
                {rules.data.items.map((r) => {
                  const key = `${r.insurance_code}-${r.article_no}`;
                  const expanded = open === key;
                  return (
                    <Fragment key={key}>
                      <tr
                        className="cursor-pointer border-b hover:bg-gray-50"
                        onClick={() => setOpen(expanded ? null : key)}
                      >
                        <td className="p-1 whitespace-nowrap">{r.insurance_code}</td>
                        <td className="p-1">{r.article_no}</td>
                        <td className="p-1">{r.title}</td>
                        <td className="p-1">{r.section ?? "—"}</td>
                        <td className="p-1 whitespace-nowrap">
                          {r.page_start}
                          {r.page_end !== r.page_start && `–${r.page_end}`}
                        </td>
                        <td className="p-1 whitespace-nowrap">
                          {r.embedding_models.length === 0
                            ? "✘ 無"
                            : `✔ ${r.embedding_dimensions} 維 · ${r.embedding_models.join("、")}`}
                        </td>
                      </tr>
                      {expanded && (
                        <tr className="border-b bg-gray-50">
                          <td colSpan={6} className="p-3">
                            <p className="mb-1 text-xs text-gray-500">
                              {r.insurance_name} {r.chapter}（{r.source_file}）
                            </p>
                            <pre className="whitespace-pre-wrap text-sm">{r.content}</pre>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="flex gap-2">
            <Button
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              disabled={offset === 0}
              className="rounded-md border px-3 py-1 hover:bg-gray-100 data-[disabled]:opacity-50"
            >
              上一頁
            </Button>
            <Button
              onClick={() => setOffset(offset + PAGE_SIZE)}
              disabled={offset + PAGE_SIZE >= total}
              className="rounded-md border px-3 py-1 hover:bg-gray-100 data-[disabled]:opacity-50"
            >
              下一頁
            </Button>
          </div>
        </>
      )}
    </section>
  );
}
