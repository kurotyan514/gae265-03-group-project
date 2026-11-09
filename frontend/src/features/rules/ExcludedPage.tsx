import { Button } from "@base-ui/react/button";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import {
  deleteExcludedMutation,
  listAdminRulesOptions,
  listExcludedOptions,
  listInsurancesOptions,
  restoreExcludedMutation,
} from "../../client/@tanstack/react-query.gen";
import type { ExcludedOut } from "../../client/types.gen";

const PAGE_SIZE = 50;

function errorText(error: unknown): string {
  const detail = (error as { detail?: unknown } | null)?.detail;
  return typeof detail === "string" ? detail : "操作失敗，請稍後再試。";
}

/**
 * 不收錄區：在條文維護被設成不收錄的條文（或整個險種）。做錯了可以單條收錄回來，不用整本重新上傳；
 * 收錄回來會重新寫入條文並只算這幾條的向量，沿用原本的 id。
 */
export function ExcludedPage() {
  const queryClient = useQueryClient();
  const [code, setCode] = useState("");
  const [text, setText] = useState("");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ ok: boolean; lines: string[] } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  const list = useQuery({
    ...listExcludedOptions({
      query: {
        limit: PAGE_SIZE,
        offset,
        ...(code ? { insurance_code: code } : {}),
        ...(query ? { q: query } : {}),
      },
    }),
    placeholderData: (previous) => previous,
  });
  const total = list.data?.total ?? 0;
  const items = list.data?.items ?? [];

  async function refresh() {
    await queryClient.invalidateQueries({ queryKey: listExcludedOptions().queryKey });
    await queryClient.invalidateQueries({ queryKey: listAdminRulesOptions().queryKey });
    await queryClient.invalidateQueries({ queryKey: listInsurancesOptions().queryKey });
  }

  const restore = useMutation({
    ...restoreExcludedMutation(),
    onSuccess: async (data) => {
      setNotice({
        ok: data.skipped.length === 0,
        lines: [
          data.message,
          ...data.skipped.map((s) => `${s.insurance_code} 第 ${s.article_no} 條略過：${s.reason}`),
        ],
      });
      await refresh();
    },
    onError: (error) => setNotice({ ok: false, lines: [errorText(error)] }),
  });
  const remove = useMutation({
    ...deleteExcludedMutation(),
    onSuccess: async (data) => {
      setConfirmDelete(null);
      setNotice({ ok: true, lines: [data.message] });
      await refresh();
    },
    onError: (error) => setNotice({ ok: false, lines: [errorText(error)] }),
  });

  const wholeInsuranceIds = items.filter((i) => i.whole_insurance).map((i) => i.id);

  return (
    <section className="space-y-4" data-testid="excluded-page">
      <p className="text-sm text-gray-600">
        在條文維護設成「不收錄」的條文會先放在這裡。收錄回來會重新寫入條文、只重算這幾條的向量，沿用原本的
        id； 條文表已經有同一條（例如重新上傳又讀進來了）的會略過。
      </p>
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          setQuery(text.trim());
          setCode(code.trim());
          setOffset(0);
        }}
      >
        <label className="space-y-1">
          <span className="block font-medium">險種代碼</span>
          <input
            value={code}
            onChange={(e) => setCode(e.target.value)}
            className="rounded-md border px-2 py-1"
            placeholder="例如 CHUBB10"
            data-testid="excluded-code"
          />
        </label>
        <label className="space-y-1">
          <span className="block font-medium">標題或內文包含</span>
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            className="rounded-md border px-2 py-1"
            data-testid="excluded-text"
          />
        </label>
        <Button type="submit" className="rounded-md border px-3 py-1 hover:bg-gray-100">
          篩選
        </Button>
        {wholeInsuranceIds.length > 0 && code && (
          <Button
            type="button"
            disabled={restore.isPending}
            onClick={() => restore.mutate({ body: { ids: wholeInsuranceIds } })}
            className="rounded-md border border-green-700 px-3 py-1 text-green-900 hover:bg-green-50 disabled:opacity-50"
            data-testid="restore-insurance"
          >
            整個險種收錄回來（{wholeInsuranceIds.length} 條）
          </Button>
        )}
      </form>

      {notice && (
        <div
          role={notice.ok ? "status" : "alert"}
          className={`rounded-md px-3 py-2 text-sm ${notice.ok ? "bg-green-50 text-green-900" : "bg-red-50 text-red-900"}`}
          data-testid="excluded-notice"
        >
          {notice.lines.map((l) => (
            <p key={l} className="m-0">
              {l}
            </p>
          ))}
        </div>
      )}
      {list.error && (
        <p role="alert" className="text-red-700">
          無法讀取不收錄區：{errorText(list.error)}
        </p>
      )}
      {list.isPending && !list.error && <p>讀取中…</p>}

      {list.data && (
        <>
          <p data-testid="excluded-total">
            共 {total} 筆{total === 0 && "；目前沒有不收錄的條文"}
          </p>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left text-sm">
              <thead>
                <tr className="border-b">
                  <th className="p-1">險種</th>
                  <th className="p-1">條</th>
                  <th className="p-1">標題</th>
                  <th className="p-1">章／節</th>
                  <th className="p-1">原因</th>
                  <th className="p-1">時間</th>
                  <th className="p-1" />
                </tr>
              </thead>
              <tbody>
                {items.map((r) => (
                  <ExcludedRow
                    key={r.id}
                    r={r}
                    expanded={open === r.id}
                    onToggle={() => setOpen(open === r.id ? null : r.id)}
                    busy={restore.isPending || remove.isPending}
                    confirming={confirmDelete === r.id}
                    onAskDelete={() => setConfirmDelete(r.id)}
                    onCancelDelete={() => setConfirmDelete(null)}
                    onRestore={() => restore.mutate({ body: { ids: [r.id] } })}
                    onDelete={() => remove.mutate({ path: { excluded_id: r.id } })}
                  />
                ))}
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

function ExcludedRow({
  r,
  expanded,
  onToggle,
  busy,
  confirming,
  onAskDelete,
  onCancelDelete,
  onRestore,
  onDelete,
}: {
  r: ExcludedOut;
  expanded: boolean;
  onToggle: () => void;
  busy: boolean;
  confirming: boolean;
  onAskDelete: () => void;
  onCancelDelete: () => void;
  onRestore: () => void;
  onDelete: () => void;
}) {
  return (
    <Fragment>
      <tr
        className="cursor-pointer border-b align-top hover:bg-gray-50"
        onClick={onToggle}
        data-testid={`excluded-${r.insurance_code}-${r.article_no}`}
      >
        <td className="p-1 whitespace-nowrap">
          {r.insurance_code}
          {r.whole_insurance && <span className="block text-xs text-gray-600">整個險種</span>}
        </td>
        <td className="p-1">{r.article_no}</td>
        <td className="p-1">{r.title}</td>
        <td className="p-1">
          {r.section ?? "—"}
          {r.subsection && <span className="block text-gray-600">{r.subsection}</span>}
        </td>
        <td className="p-1">{r.reason ?? "—"}</td>
        <td className="p-1 whitespace-nowrap">{new Date(r.excluded_at).toLocaleString("zh-TW")}</td>
        <td className="p-1 text-xs">
          {r.in_catalog && (
            <span className="block rounded bg-amber-100 px-1.5 py-0.5 text-amber-900">
              條文表已有同一條
            </span>
          )}
          {!r.insurance_exists && (
            <span className="block text-gray-600">險種已不在，收錄時一併建立</span>
          )}
        </td>
      </tr>
      {expanded && (
        <tr className="border-b bg-gray-50">
          <td colSpan={7} className="space-y-2 p-3">
            <p className="text-xs text-gray-500">
              {r.insurance_name} {r.chapter}
            </p>
            <pre className="whitespace-pre-wrap text-sm">{r.content}</pre>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                type="button"
                disabled={busy}
                onClick={onRestore}
                className="rounded-md border border-green-700 px-3 py-1 text-sm text-green-900 hover:bg-green-50 disabled:opacity-50"
                data-testid="restore-rule"
              >
                收錄回來
              </Button>
              {!confirming ? (
                <Button
                  type="button"
                  onClick={onAskDelete}
                  className="rounded-md border border-red-300 px-3 py-1 text-sm text-red-800 hover:bg-red-50"
                  data-testid="delete-excluded"
                >
                  永久刪除
                </Button>
              ) : (
                <span className="flex items-center gap-2 text-sm text-red-900">
                  刪除後就收錄不回來了，確定嗎？
                  <Button
                    type="button"
                    disabled={busy}
                    onClick={onDelete}
                    className="rounded-md bg-red-800 px-3 py-1 text-white disabled:opacity-50"
                    data-testid="delete-excluded-yes"
                  >
                    確定刪除
                  </Button>
                  <Button
                    type="button"
                    onClick={onCancelDelete}
                    className="rounded-md border bg-white px-3 py-1 hover:bg-gray-100"
                  >
                    取消
                  </Button>
                </span>
              )}
            </div>
          </td>
        </tr>
      )}
    </Fragment>
  );
}
