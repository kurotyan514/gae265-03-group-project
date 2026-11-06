import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { listClaimPackageSamples } from "../client";
import type { ClaimPackageSampleOut } from "../client/types.gen";
import { missingItems } from "../features/package/blanks";
import { ClaimLetter } from "../features/package/ClaimLetter";
import { MissingBlanksDialog } from "../features/package/MissingBlanksDialog";

export const Route = createFileRoute("/dev/package")({
  component: PackageSamplesPage,
});

const buttonClass = "rounded-md border px-3 py-1 hover:bg-gray-100";
const activeClass = "bg-gray-900 text-white hover:bg-gray-900";

/**
 * 打包寄送測試台：用虛構的範例事件，看 7 號產生的送件信與寄出前的提醒。
 * 信件由後端 7 號真正的程式產生；不需要登入、不寫資料庫、不連 Google，也不會真的寄出。
 */
function PackageSamplesPage() {
  const [samples, setSamples] = useState<ClaimPackageSampleOut[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [missing, setMissing] = useState<string[]>([]);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    listClaimPackageSamples().then((res) => {
      if (res.data?.length) {
        setSamples(res.data);
        return;
      }
      const status = res.response?.status;
      setError(
        status === 404
          ? "後端沒有範例的 API（404）：後端可能還在跑舊的程式，請重啟後端（停掉 make up 再重跑）"
          : `讀不到範例（${status ? `HTTP ${status}` : "後端沒有回應"}），請確認後端有開`,
      );
    });
  }, []);

  const sample = samples.find((s) => s.key === selected);

  const send = () => {
    if (!sample) return;
    const items = missingItems(sample.package.subject, sample.package.body);
    if (items.length > 0) {
      setMissing(items);
      return;
    }
    setNote("信裡沒有空格，正式流程會直接寄出；這是開發用頁面，不會真的寄出。");
  };

  return (
    <section className="space-y-4">
      <h2 className="text-xl font-bold">打包寄送</h2>
      <p className="text-sm text-gray-600">
        選一個範例，看 7 號在這種情況下產生的送件信。範例都是虛構的，不會真的寄出。
      </p>
      {error && <p className="text-red-700">{error}</p>}
      <div className="flex flex-wrap gap-2">
        {samples.map((s) => (
          <button
            key={s.key}
            type="button"
            className={`${buttonClass} ${s.key === selected ? activeClass : ""}`}
            onClick={() => {
              setSelected(s.key);
              setNote("");
            }}
          >
            {s.title}
          </button>
        ))}
      </div>
      {sample && (
        <div className="space-y-3">
          <p className="text-sm text-gray-600">{sample.description}</p>
          <ClaimLetter pkg={sample.package} />
          <button type="button" className={buttonClass} onClick={send}>
            寄出
          </button>
          {note && <p className="text-sm">{note}</p>}
        </div>
      )}
      <MissingBlanksDialog items={missing} onClose={() => setMissing([])} />
    </section>
  );
}
