import { Button } from "@base-ui/react/button";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import {
  editAdminRuleMutation,
  listAdminRulesOptions,
  listAllRulesOptions,
  listInsurancesOptions,
} from "../../client/@tanstack/react-query.gen";
import type { DevRuleOut } from "../../client/types.gen";

function errorText(error: unknown): string {
  const detail = (error as { detail?: unknown } | null)?.detail;
  return typeof detail === "string" ? detail : "儲存失敗，請稍後再試。";
}

/**
 * 修改一條條文的標題與內文：存檔時後端會重新算這一條的向量（標題與內文都進檢索用的文字）。
 * 改動只存在資料庫，重新上傳合訂本或 make ingest 會用 PDF 的內容蓋回去。
 */
function RuleEditor({ rule }: { rule: DevRuleOut }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(rule.title);
  const [content, setContent] = useState(rule.content);
  const [reason, setReason] = useState("");
  const [saved, setSaved] = useState<string | null>(null);
  const save = useMutation({
    ...editAdminRuleMutation(),
    onSuccess: async (data) => {
      setEditing(false);
      setSaved(`已儲存，向量已重新計算（${data.embedding_dimensions} 維）`);
      await queryClient.invalidateQueries({ queryKey: listAdminRulesOptions().queryKey });
    },
  });
  const changed = title.trim() !== rule.title || content.trim() !== rule.content;

  if (!editing) {
    return (
      <div className="mt-2 flex items-center gap-3">
        <Button
          type="button"
          onClick={() => {
            setTitle(rule.title);
            setContent(rule.content);
            setReason("");
            setSaved(null);
            save.reset();
            setEditing(true);
          }}
          className="rounded-md border px-3 py-1 text-sm hover:bg-gray-100"
          data-testid="edit-rule"
        >
          編輯標題與內文
        </Button>
        {saved && (
          <span role="status" className="text-sm text-green-800" data-testid="edit-result">
            {saved}
          </span>
        )}
      </div>
    );
  }

  return (
    <form
      className="mt-3 space-y-2 rounded-md border bg-white p-3"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate({
          path: { insurance_code: rule.insurance_code, article_no: rule.article_no },
          body: { title: title.trim(), content: content.trim(), reason: reason.trim() || null },
        });
      }}
    >
      <label className="block space-y-1">
        <span className="block text-sm font-medium">標題</span>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          className="w-full rounded-md border px-2 py-1"
          data-testid="edit-title"
        />
      </label>
      <label className="block space-y-1">
        <span className="block text-sm font-medium">內文</span>
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          rows={14}
          className="w-full rounded-md border px-2 py-1 font-mono text-sm"
          data-testid="edit-content"
        />
      </label>
      <label className="block space-y-1">
        <span className="block text-sm font-medium">為什麼改（選填，只寫進日誌）</span>
        <input
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          className="w-full rounded-md border px-2 py-1"
          placeholder="例如：PDF 文字層漏了一行"
          data-testid="edit-reason"
        />
      </label>
      <p className="text-xs text-gray-600">
        存檔時會重新計算這一條的向量。改動只存在資料庫：重新上傳合訂本或 make ingest 會用 PDF
        的內容蓋回去。
      </p>
      {save.isError && (
        <p role="alert" className="text-sm text-red-700" data-testid="edit-error">
          {errorText(save.error)}
        </p>
      )}
      <div className="flex gap-2">
        <Button
          type="submit"
          disabled={!changed || !title.trim() || !content.trim() || save.isPending}
          className="rounded-md bg-gray-900 px-3 py-1 text-sm text-white disabled:opacity-50"
          data-testid="save-rule"
        >
          {save.isPending ? "重新計算向量中…" : "儲存並重新計算向量"}
        </Button>
        <Button
          type="button"
          onClick={() => setEditing(false)}
          disabled={save.isPending}
          className="rounded-md border px-3 py-1 text-sm hover:bg-gray-100 disabled:opacity-50"
          data-testid="cancel-edit"
        >
          取消
        </Button>
      </div>
    </form>
  );
}

const PAGE_SIZE = 50;

/**
 * 瀏覽資料庫裡全部條文（含向量狀態），用來核對匯入有沒有漏。
 * `source="admin"` 讀後台的清單（要登入），`editable` 時展開的條文可以修改標題與內文。
 * 開發用的 `/dev/rules` 讀 `/rules`，唯讀。
 */
export function RulesBrowser({
  source,
  editable = false,
}: {
  source: "dev" | "admin";
  editable?: boolean;
}) {
  const [code, setCode] = useState("");
  const [text, setText] = useState("");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState<string | null>(null);

  const insurances = useQuery(listInsurancesOptions());
  const params = {
    query: {
      limit: PAGE_SIZE,
      offset,
      ...(code ? { insurance_code: code } : {}),
      ...(query ? { q: query } : {}),
    },
  };
  const rules = useQuery({
    ...(source === "admin" ? listAdminRulesOptions(params) : listAllRulesOptions(params)),
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
                            {editable && <RuleEditor key={key} rule={r} />}
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
