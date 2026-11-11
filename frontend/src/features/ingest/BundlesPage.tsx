import { Button } from "@base-ui/react/button";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { getBundle } from "../../client";
import { listBundlesOptions } from "../../client/@tanstack/react-query.gen";
import type { SplitCreated, SplitOut } from "../../client/types.gen";
import { BundleEditor } from "./BundleEditor";

const STATUS_LABEL: Record<string, string> = { draft: "草稿", confirmed: "已確認" };

/** 合訂本：上傳後偵測各險種的起點，管理者確認；確認過的清單之後上傳同一份直接沿用。 */
export function BundlesPage() {
  const queryClient = useQueryClient();
  const list = useQuery(listBundlesOptions());
  const [split, setSplit] = useState<SplitOut | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = () => queryClient.invalidateQueries({ queryKey: listBundlesOptions().queryKey });

  async function upload(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      const res = await fetch("/api/v1/ingest/bundles", {
        method: "POST",
        body: new FormData(e.currentTarget),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(
          typeof body?.detail === "string" ? body.detail : `上傳失敗（HTTP ${res.status}）`,
        );
      }
      const created = (await res.json()) as SplitCreated;
      setSplit(created);
      setNotice(
        created.reused
          ? created.status === "confirmed"
            ? "這份合訂本以前確認過，直接沿用那份清單"
            : "這份合訂本以前上傳過，接續上次的草稿"
          : `偵測到 ${created.sections.length} 個區段，請逐一確認`,
      );
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function open(id: string) {
    setError(null);
    setNotice(null);
    const { data } = await getBundle({ path: { split_id: id } });
    if (data) setSplit(data);
    else setError("讀不到這份清單");
  }

  return (
    <section className="space-y-6">
      <form onSubmit={upload} className="flex flex-wrap items-end gap-3" data-testid="bundle-form">
        <label className="space-y-1">
          <span className="block font-medium">合訂本 PDF</span>
          <input
            type="file"
            name="file"
            accept="application/pdf"
            required
            data-testid="bundle-file"
          />
        </label>
        <label className="space-y-1">
          <span className="block font-medium">保險公司（選填）</span>
          <input
            name="company"
            placeholder="例如 ○○產物（確認前一定要填）"
            className="rounded-md border px-2 py-1"
          />
        </label>
        <Button
          type="submit"
          disabled={busy}
          className="rounded-md bg-gray-900 px-3 py-1 text-white disabled:opacity-50"
        >
          上傳並分析
        </Button>
      </form>
      {notice && (
        <p className="text-green-800" data-testid="bundle-notice">
          {notice}
        </p>
      )}
      {error && (
        <p role="alert" className="text-red-700" data-testid="bundle-upload-error">
          {error}
        </p>
      )}

      <div className="grid gap-6 md:grid-cols-[18rem_1fr]">
        <ul className="space-y-1" aria-label="拆分清單" data-testid="bundles">
          {list.data?.length === 0 && <li className="text-gray-500">還沒有拆分清單</li>}
          {list.data?.map((b) => (
            <li key={b.id}>
              <button
                type="button"
                onClick={() => open(b.id)}
                className={`w-full rounded-md border px-3 py-2 text-left hover:bg-gray-100 ${
                  split?.id === b.id ? "border-gray-900" : ""
                }`}
              >
                <span className="block font-medium">{b.filename}</span>
                <span className="text-sm text-gray-600">
                  {b.company || "（未填公司）"} · {b.section_count} 個區段 ·{" "}
                  {STATUS_LABEL[b.status] ?? b.status}
                </span>
              </button>
            </li>
          ))}
        </ul>

        {split ? (
          // 換一份清單就整個重新掛載，編輯中的狀態不會帶到別份
          <BundleEditor
            key={split.id}
            split={split}
            onSaved={(next) => {
              setSplit(next);
              refresh();
            }}
          />
        ) : (
          <p className="text-gray-500">上傳合訂本，或從左邊選一份拆分清單。</p>
        )}
      </div>
    </section>
  );
}
