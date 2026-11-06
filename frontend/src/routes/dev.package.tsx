import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { listClaimPackageSamples } from "../client";
import type { ClaimPackageSampleOut } from "../client/types.gen";
import { GoogleConsentDialog } from "../features/google/GoogleConsentDialog";
import type { GooglePurpose } from "../features/google/google";
import { fillBlanks, missingItems } from "../features/package/blanks";
import { ClaimLetter } from "../features/package/ClaimLetter";
import { DraftQuestionDialog } from "../features/package/DraftQuestionDialog";

export const Route = createFileRoute("/dev/package")({
  component: PackageSamplesPage,
});

const buttonClass =
  "rounded-md border px-3 py-1 hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-50";
const activeClass = "bg-gray-900 text-white hover:bg-gray-900";
const primaryClass =
  "rounded-md bg-blue-600 px-3 py-1 text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50";

/**
 * 送件的畫面：
 * ask 問要不要幫忙寄；preview 預覽並填空格；sent 寄出後結案；
 * drafted 建好草稿後結案；closed 自己處理、不建草稿，直接結案。
 */
type Step = "ask" | "preview" | "sent" | "drafted" | "closed";

/** 要授權是為了做什麼：看預覽、寄出、建立草稿。 */
type Intent = "preview" | "send" | "draft";

/** 模擬的 Google 授權：開發頁不登入、不連 Google，用勾選代表授權狀態（ADR-0020）。 */
type Grants = Record<GooglePurpose, boolean>;

/** 還缺哪個授權：寄信與建立草稿都要從 Drive 讀附件，所以先 Drive 再 Gmail（ADR-0020）。 */
function nextMissing(grants: Grants): GooglePurpose | null {
  if (!grants.drive) return "drive";
  if (!grants.gmail) return "gmail";
  return null;
}

/** 寄件者：正式頁面是使用者登入的 Gmail；開發頁沒有登入，用範例信箱代替。 */
const SENDER = "you@example.com";

/** 收件者的 email 格式：有 @，@ 後面有點，中間沒有空白。 */
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const CLOSED_TEXT: Partial<Record<Step, string>> = {
  sent: "已用你的 Gmail 寄給保險公司（模擬，沒有真的寄出）。",
  drafted: "已在你的 Gmail 建立草稿（模擬，沒有真的建立），請到 Gmail 修改後自己寄出。",
  closed: "沒有建立草稿，請自己寄給保險公司。",
};

/**
 * 打包寄送測試台：用虛構的範例事件，走一次送件的畫面。
 * 信件由後端 7 號真正的程式產生；不需要登入、不寫資料庫、不連 Google，也不會真的寄出。
 */
function PackageSamplesPage() {
  const [samples, setSamples] = useState<ClaimPackageSampleOut[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [step, setStep] = useState<Step>("ask");
  const [values, setValues] = useState<Record<string, string>>({});
  const [recipient, setRecipient] = useState("");
  // 一般情況上傳文件時就授權過 Drive，所以預設 Drive 可以用、Gmail 還沒授權
  const [grants, setGrants] = useState<Grants>({ drive: true, gmail: false });
  const [consent, setConsent] = useState<GooglePurpose | null>(null);
  const [intent, setIntent] = useState<Intent>("preview");
  const [askingDraft, setAskingDraft] = useState(false);
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
  const filled = sample && {
    ...sample.package,
    subject: fillBlanks(sample.package.subject, values),
    body: fillBlanks(sample.package.body, values),
  };
  const remaining = filled ? missingItems(filled.subject, filled.body) : [];
  const recipientProblem = !recipient.trim()
    ? "請填寫收件者"
    : EMAIL.test(recipient.trim())
      ? ""
      : "收件者的 email 格式不對";

  /** 換範例或重新開始：回到第一個畫面，清掉填的內容（授權狀態保留）。 */
  const restart = (key: string | null) => {
    setSelected(key);
    setStep("ask");
    setValues({});
    setRecipient("");
    setConsent(null);
    setAskingDraft(false);
  };

  const finish = (done: Intent) => {
    if (done === "preview") setStep("preview");
    if (done === "send") setStep("sent");
    if (done === "draft") setStep("drafted");
  };

  /** 要做某件事之前：缺授權就先說明（先 Drive 再 Gmail），都有了就直接做。 */
  const withGrants = (next: Intent) => {
    setIntent(next);
    const purpose = nextMissing(grants);
    if (purpose) setConsent(purpose);
    else finish(next);
  };

  /** 在說明視窗按同意（模擬）：記下授權，還缺就接著說明下一個，都有了就做原本要做的事。 */
  const grant = (purpose: GooglePurpose) => {
    const updated = { ...grants, [purpose]: true };
    setGrants(updated);
    const next = nextMissing(updated);
    setConsent(next);
    if (!next) finish(intent);
  };

  /** 在說明視窗按先不要：看預覽照樣進預覽；寄出留在預覽；建立草稿回到草稿的問題。 */
  const declineGrant = () => {
    setConsent(null);
    if (intent === "preview") setStep("preview");
    if (intent === "draft") setAskingDraft(true);
  };

  const closedText = CLOSED_TEXT[step];

  return (
    <section className="space-y-4">
      <h2 className="text-xl font-bold">打包寄送</h2>
      <p className="text-sm text-gray-600">
        選一個範例，走一次送件的畫面，看 7 號產生的送件信。範例都是虛構的，Google
        授權是模擬的，不會真的寄出或建立草稿。
      </p>
      {error && <p className="text-red-700">{error}</p>}
      <div className="flex flex-wrap gap-2">
        {samples.map((s) => (
          <button
            key={s.key}
            type="button"
            className={`${buttonClass} ${s.key === selected ? activeClass : ""}`}
            onClick={() => restart(s.key)}
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
      {sample && filled && (
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
                <button type="button" className={buttonClass} onClick={() => setAskingDraft(true)}>
                  我自己處理就好
                </button>
                <button
                  type="button"
                  className={primaryClass}
                  onClick={() => withGrants("preview")}
                >
                  好險有你小助理幫我送出
                </button>
              </div>
            </div>
          )}
          {step === "preview" && (
            <>
              <p className="text-sm">
                請填好收件者和標色的地方，全部填完才能寄出。寄件者是你自己的 Gmail
                （開發頁沒有登入，用範例信箱代替）。
              </p>
              <ClaimLetter
                pkg={sample.package}
                values={values}
                onFill={(item, value) => setValues({ ...values, [item]: value })}
                sender={SENDER}
                recipient={recipient}
                onRecipient={setRecipient}
              />
              {recipientProblem && (
                <p data-testid="recipient-problem" className="text-sm text-red-700">
                  {recipientProblem}
                </p>
              )}
              {remaining.length > 0 && (
                <div data-testid="missing" className="rounded-md bg-yellow-50 p-2 text-sm">
                  <p>還有 {remaining.length} 項要填寫：</p>
                  <ul className="list-disc pl-5">
                    {remaining.map((item) => (
                      <li key={item} data-testid="missing-item">
                        {item}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              <button
                type="button"
                className={primaryClass}
                disabled={remaining.length > 0 || recipientProblem !== ""}
                onClick={() => withGrants("send")}
              >
                寄出
              </button>
            </>
          )}
          {closedText && (
            <div data-testid="closed" className="space-y-3">
              <p className="rounded-md bg-green-50 p-2 text-green-800">
                {closedText}此事件已結案，不能再新增狀況或修改。
              </p>
              {step === "sent" && (
                <ClaimLetter pkg={filled} sender={SENDER} recipient={recipient.trim()} />
              )}
              <button type="button" className={buttonClass} onClick={() => restart(selected)}>
                重新開始這個範例（開發用）
              </button>
            </div>
          )}
        </div>
      )}
      <GoogleConsentDialog
        purpose={consent}
        next="/dev/package"
        onClose={declineGrant}
        onSimulatedGrant={grant}
      />
      <DraftQuestionDialog
        open={askingDraft}
        onYes={() => {
          setAskingDraft(false);
          withGrants("draft");
        }}
        onNo={() => {
          setAskingDraft(false);
          setStep("closed");
        }}
        onDismiss={() => setAskingDraft(false)}
      />
    </section>
  );
}
