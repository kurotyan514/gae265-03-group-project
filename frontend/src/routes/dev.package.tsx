import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { listClaimPackageSamples } from "../client";
import type { ClaimPackageSampleOut } from "../client/types.gen";
import { GoogleConsentDialog } from "../features/google/GoogleConsentDialog";
import type { GooglePurpose } from "../features/google/google";
import { missingItems } from "../features/package/blanks";
import { ClaimLetter } from "../features/package/ClaimLetter";
import { MissingBlanksDialog } from "../features/package/MissingBlanksDialog";

export const Route = createFileRoute("/dev/package")({
  component: PackageSamplesPage,
});

const buttonClass = "rounded-md border px-3 py-1 hover:bg-gray-100";
const activeClass = "bg-gray-900 text-white hover:bg-gray-900";
const primaryClass = "rounded-md bg-blue-600 px-3 py-1 text-white hover:bg-blue-700";

/** 送件的畫面：先問要不要幫忙寄（ask），再看信（preview 由我們寄；self 使用者自己寄）。 */
type Step = "ask" | "preview" | "self";

/** 模擬的 Google 授權：開發頁不登入、不連 Google，用勾選代表授權狀態（ADR-0020）。 */
type Grants = Record<GooglePurpose, boolean>;

/** 還缺哪個授權：寄信要從 Drive 讀附件，所以先 Drive 再 Gmail（ADR-0020）。 */
function nextMissing(grants: Grants): GooglePurpose | null {
  if (!grants.drive) return "drive";
  if (!grants.gmail) return "gmail";
  return null;
}

/**
 * 打包寄送測試台：用虛構的範例事件，走一次送件的畫面。
 * 信件由後端 7 號真正的程式產生；不需要登入、不寫資料庫、不連 Google，也不會真的寄出。
 */
function PackageSamplesPage() {
  const [samples, setSamples] = useState<ClaimPackageSampleOut[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [step, setStep] = useState<Step>("ask");
  const [grants, setGrants] = useState<Grants>({ drive: false, gmail: false });
  const [consent, setConsent] = useState<GooglePurpose | null>(null);
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

  const choose = (key: string) => {
    setSelected(key);
    setStep("ask");
    setNote("");
  };

  /** 按「好險有你小助理幫我送出」：缺授權就先說明，都有了才看信。 */
  const assist = () => {
    const purpose = nextMissing(grants);
    if (purpose) setConsent(purpose);
    else setStep("preview");
  };

  /** 在說明視窗按同意（模擬）：記下授權，還缺就接著說明下一個，都有了就看信。 */
  const grant = (purpose: GooglePurpose) => {
    const updated = { ...grants, [purpose]: true };
    setGrants(updated);
    const next = nextMissing(updated);
    setConsent(next);
    if (!next) setStep("preview");
  };

  const send = () => {
    if (!sample) return;
    const items = missingItems(sample.package.subject, sample.package.body);
    if (items.length > 0) {
      setMissing(items);
      return;
    }
    setNote("信裡沒有空格，正式流程會直接寄出；這是開發用頁面，不會真的寄出。");
  };

  const copy = (label: string, text: string) => {
    navigator.clipboard.writeText(text).then(
      () => setNote(`已複製${label}。`),
      () => setNote(`無法複製${label}，請直接選取文字複製。`),
    );
  };

  return (
    <section className="space-y-4">
      <h2 className="text-xl font-bold">打包寄送</h2>
      <p className="text-sm text-gray-600">
        選一個範例，走一次送件的畫面，看 7 號產生的送件信。範例都是虛構的，Google
        授權是模擬的，不會真的寄出。
      </p>
      {error && <p className="text-red-700">{error}</p>}
      <div className="flex flex-wrap gap-2">
        {samples.map((s) => (
          <button
            key={s.key}
            type="button"
            className={`${buttonClass} ${s.key === selected ? activeClass : ""}`}
            onClick={() => choose(s.key)}
          >
            {s.title}
          </button>
        ))}
      </div>
      <fieldset className="flex flex-wrap gap-4 text-sm">
        <legend className="sr-only">模擬的 Google 授權</legend>
        <label className="flex items-center gap-1">
          <input
            type="checkbox"
            checked={grants.drive}
            onChange={(e) => setGrants({ ...grants, drive: e.target.checked })}
          />
          模擬：Google Drive 已授權
        </label>
        <label className="flex items-center gap-1">
          <input
            type="checkbox"
            checked={grants.gmail}
            onChange={(e) => setGrants({ ...grants, gmail: e.target.checked })}
          />
          模擬：Gmail 已授權
        </label>
      </fieldset>
      {sample && (
        <div className="space-y-3">
          <p className="text-sm text-gray-600">{sample.description}</p>
          <h3 className="text-lg font-bold">送件</h3>
          <p className="text-gray-600">{sample.package.subject}</p>
          {step === "ask" && (
            <div className="space-y-2">
              <p className="font-bold">要由我們用你的 Gmail 幫你寄給保險公司嗎？</p>
              <p className="text-sm text-gray-600">
                寄件者是你自己的 Gmail；Gmail 權限只用來寄這封信。
              </p>
              <div className="flex flex-wrap gap-2">
                <button type="button" className={buttonClass} onClick={() => setStep("self")}>
                  我自己處理就好
                </button>
                <button type="button" className={primaryClass} onClick={assist}>
                  好險有你小助理幫我送出
                </button>
              </div>
            </div>
          )}
          {step === "preview" && (
            <>
              <ClaimLetter pkg={sample.package} />
              <div className="flex flex-wrap gap-2">
                <button type="button" className={buttonClass} onClick={() => setStep("ask")}>
                  返回
                </button>
                <button type="button" className={primaryClass} onClick={send}>
                  寄出
                </button>
              </div>
            </>
          )}
          {step === "self" && (
            <>
              <p className="text-sm">
                請把主旨與內文複製到你的信箱，附上附件清單裡的文件，自己寄給保險公司。
              </p>
              <ClaimLetter pkg={sample.package} />
              <div className="flex flex-wrap gap-2">
                <button type="button" className={buttonClass} onClick={() => setStep("ask")}>
                  返回
                </button>
                <button
                  type="button"
                  className={buttonClass}
                  onClick={() => copy("主旨", sample.package.subject)}
                >
                  複製主旨
                </button>
                <button
                  type="button"
                  className={buttonClass}
                  onClick={() => copy("內文", sample.package.body)}
                >
                  複製內文
                </button>
              </div>
            </>
          )}
          {note && <p className="text-sm">{note}</p>}
        </div>
      )}
      <GoogleConsentDialog
        purpose={consent}
        next="/dev/package"
        onClose={() => setConsent(null)}
        onSimulatedGrant={grant}
      />
      <MissingBlanksDialog items={missing} onClose={() => setMissing([])} />
    </section>
  );
}
