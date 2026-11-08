import { Button } from "@base-ui/react/button";
import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { getIncidentPackage, submitIncident } from "../client";
import type { ClaimPackage, SubmissionOut } from "../client/types.gen";
import { GoogleAuthResult } from "../features/google/GoogleAuthResult";
import { GoogleConsentDialog } from "../features/google/GoogleConsentDialog";
import type { GooglePurpose } from "../features/google/google";
import { useGoogleGrant } from "../features/google/useGoogleGrant";
import { box, errorText, primary, secondary, useIncident } from "../features/incident/shared";
import { fillBlanks, missingItems } from "../features/package/blanks";
import { ClaimLetter } from "../features/package/ClaimLetter";
import { DraftQuestionDialog } from "../features/package/DraftQuestionDialog";

export const Route = createFileRoute("/_authed/incident/$id/submit")({
  component: SubmitStep,
});

/** ask：問要不要幫忙寄；preview：預覽信、填空格與收件者。結案後不看這個，看結果。 */
type Step = "ask" | "preview";

/** 要授權是為了做什麼：看預覽、寄出、建立草稿。 */
type Intent = "preview" | "send" | "draft";

/** 收件者的 email 格式：有 @，@ 後面有點，中間沒有空白。 */
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const RESULT_TEXT: Record<string, string> = {
  sent: "已用你的 Gmail 寄給保險公司。",
  drafted: "已在你的 Gmail 建立草稿，請到 Gmail 修改後自己寄出。",
  self_submitted: "沒有建立草稿，請自己寄給保險公司。",
};

/**
 * 導向 Google 授權會整頁離開，回來時要接得上：已填的空格、收件者與走到哪一步
 * 暫存在這個分頁的 sessionStorage（結案後清掉）。
 */
type Saved = {
  step?: Step;
  values?: Record<string, string>;
  recipient?: string;
  intent?: Intent;
};
const storeKey = (id: string) => `incident-submit:${id}`;
function loadSaved(id: string): Saved {
  try {
    return JSON.parse(sessionStorage.getItem(storeKey(id)) ?? "{}") as Saved;
  } catch {
    return {};
  }
}
function writeSaved(id: string, data: Saved | null) {
  try {
    if (data) sessionStorage.setItem(storeKey(id), JSON.stringify(data));
    else sessionStorage.removeItem(storeKey(id));
  } catch {
    // 無痕視窗等情況存不了：只是授權回來後要重填，不影響送件
  }
}

/** 步驟 3：先問代寄或自己處理；代寄要在預覽把空格與收件者填完才能寄出；三種結果都結案（ADR-0025）。 */
function SubmitStep() {
  const { id } = Route.useParams();
  const { user } = Route.useRouteContext();
  const { data: ctx, setIncident } = useIncident(id);
  const googleUser = user.login_provider === "google";
  const grant = useGoogleGrant(googleUser);
  const [saved] = useState(() => loadSaved(id));
  const [step, setStep] = useState<Step>(saved.step ?? "ask");
  const [values, setValues] = useState<Record<string, string>>(saved.values ?? {});
  const [recipient, setRecipient] = useState(saved.recipient ?? "");
  const [intent, setIntent] = useState<Intent>(saved.intent ?? "preview");
  const [consent, setConsent] = useState<GooglePurpose | null>(null);
  const [askingDraft, setAskingDraft] = useState(saved.intent === "draft");
  const [pkg, setPkg] = useState<ClaimPackage | null>(null);
  const [result, setResult] = useState<SubmissionOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const closed = ctx?.status === "completed";

  // 授權回來：原本要看預覽就直接進預覽；要寄出或建立草稿的，讓使用者再按一次確認
  useEffect(() => {
    if (saved.intent === "preview") setStep("preview");
    if (saved.intent) writeSaved(id, { ...saved, intent: undefined });
  }, [id, saved]);

  // 進到預覽才讀信；收件者沒填時帶入 7 號的建議
  useEffect(() => {
    if (step !== "preview" || pkg || closed) return;
    getIncidentPackage({ path: { incident_id: id } }).then((res) => {
      if (!res.data) return setError(errorText(res.error, res.response?.status));
      setPkg(res.data);
      setRecipient((current) => current || res.data?.recipient_hint || "");
    });
  }, [step, pkg, closed, id]);

  if (!ctx) return null;
  const todos = ctx.todos ?? [];
  const remainingTodos = todos.filter((t) => !t.is_done && t.status !== "not_applicable").length;
  const ready = todos.length > 0 && remainingTodos === 0;

  const filled = pkg && {
    ...pkg,
    subject: fillBlanks(pkg.subject, values),
    body: fillBlanks(pkg.body, values),
  };
  const blanks = filled ? missingItems(filled.subject, filled.body) : [];
  const recipientProblem = !recipient.trim()
    ? "請填寫收件者"
    : EMAIL.test(recipient.trim())
      ? ""
      : "收件者的 email 格式不對";

  async function submit(mode: "send" | "draft" | "self") {
    setBusy(true);
    setError(null);
    const res = await submitIncident({
      path: { incident_id: id },
      body: {
        mode,
        fills: values,
        recipient: mode === "self" ? null : recipient.trim() || null,
      },
    });
    setBusy(false);
    if (!res.data) return setError(errorText(res.error, res.response?.status));
    setResult(res.data);
    if (res.data.status !== "failed") writeSaved(id, null);
    const fresh = await fetch(`/api/v1/incidents/${id}`);
    if (fresh.ok) setIncident(await fresh.json());
  }

  /** 要做某件事之前：寄信與建草稿都要從 Drive 讀附件再用 Gmail，缺哪個先說明（先 Drive 再 Gmail）。 */
  function withGrants(next: Intent) {
    setIntent(next);
    if (googleUser) {
      if (!grant.data) return setError("正在確認 Google 授權，請稍候再按一次。");
      const missing = (["drive", "gmail"] as const).find((p) => !grant.data?.[p]);
      if (missing) {
        writeSaved(id, { step, values, recipient, intent: next });
        return setConsent(missing);
      }
    }
    if (next === "preview") setStep("preview");
    if (next === "send") void submit("send");
    if (next === "draft") void submit("draft");
  }

  /** 說明視窗按「先不要」：看預覽照樣進預覽；寄出留在預覽；建立草稿回到草稿的問題。 */
  function declineGrant() {
    setConsent(null);
    if (intent === "preview") setStep("preview");
    if (intent === "draft") setAskingDraft(true);
  }

  const closedText = result ? RESULT_TEXT[result.status] : undefined;

  return (
    <div className="space-y-4">
      <GoogleAuthResult />
      <GoogleConsentDialog
        purpose={consent}
        next={`/incident/${id}/submit`}
        onClose={declineGrant}
      />
      <DraftQuestionDialog
        open={askingDraft && !closed}
        onYes={() => {
          setAskingDraft(false);
          if (!googleUser) {
            return setError("你不是用 Google 登入，沒有 Gmail 可以建立草稿。");
          }
          withGrants("draft");
        }}
        onNo={() => {
          setAskingDraft(false);
          void submit("self");
        }}
        onDismiss={() => setAskingDraft(false)}
      />
      {error && (
        <p role="alert" className="rounded-md bg-red-50 p-2 text-red-800" data-testid="error">
          {error}
        </p>
      )}
      {!googleUser && !closed && (
        <p className="rounded-md bg-gray-50 p-2 text-sm text-gray-700">
          你不是用 Google 登入，沒有 Gmail 可以寄信或建立草稿。可以先預覽信件，寄送請改用 Google
          登入。
        </p>
      )}
      {result?.status === "failed" && step !== "preview" && (
        <FailedNotice id={id} reason={result.reason} />
      )}

      {closed ? (
        <section className={box} aria-label="送件結果">
          <h2 className="font-bold">送件結果</h2>
          <p className="rounded-md bg-green-50 p-2 text-green-800" data-testid="closed">
            {closedText ?? "這個事件已結案。"}
            此事件已結案，不能再新增狀況或修改。
          </p>
          {result?.status === "sent" && filled && (
            <ClaimLetter pkg={filled} sender={user.email} recipient={recipient.trim()} />
          )}
        </section>
      ) : (
        <>
          <section className={box} aria-label="送件前確認">
            <h2 className="font-bold">送件前確認</h2>
            <p className="text-sm text-gray-700" data-testid="ready">
              {ready ? (
                "所有待辦都完成了，可以送件。"
              ) : (
                <>
                  還有 {remainingTodos} 項待辦沒完成，完成後才能送件。
                  <Link to="/incident/$id" params={{ id }} className="ml-1 underline">
                    回到待辦
                  </Link>
                </>
              )}
            </p>
          </section>

          {step === "ask" && (
            <section className={box} aria-label="送件方式" data-testid="ask">
              <h2 className="font-bold">要由我們用你的 Gmail 幫你寄給保險公司嗎？</h2>
              <p className="text-sm text-gray-600">
                寄件者是你自己的 Gmail；Gmail 權限只用來寄這封信。
              </p>
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  disabled={busy || !ready}
                  onClick={() => setAskingDraft(true)}
                  className={secondary}
                  data-testid="choose-self"
                >
                  我自己處理就好
                </Button>
                <Button
                  type="button"
                  disabled={busy || !ready}
                  onClick={() => withGrants("preview")}
                  className={primary}
                  data-testid="choose-send"
                >
                  好險有你小助理幫我送出
                </Button>
              </div>
            </section>
          )}

          {step === "preview" && (
            <section className={box} aria-label="預覽與寄出" data-testid="preview">
              <h2 className="font-bold">預覽送件信</h2>
              <p className="text-sm">
                請填好收件者和標色的地方，全部填完才能寄出。寄件者是你自己的 Gmail。
              </p>
              {pkg ? (
                <ClaimLetter
                  pkg={pkg}
                  values={values}
                  onFill={(item, value) => setValues({ ...values, [item]: value })}
                  sender={user.email}
                  recipient={recipient}
                  onRecipient={setRecipient}
                />
              ) : (
                <p className="text-sm text-gray-500">讀取送件信中…</p>
              )}
              {pkg && recipientProblem && (
                <p data-testid="recipient-problem" className="text-sm text-red-700">
                  {recipientProblem}
                </p>
              )}
              {blanks.length > 0 && (
                <div data-testid="missing" className="rounded-md bg-yellow-50 p-2 text-sm">
                  <p>還有 {blanks.length} 項要填寫：</p>
                  <ul className="list-disc pl-5">
                    {blanks.map((item) => (
                      <li key={item} data-testid="missing-item">
                        {item}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {/* 寄出失敗的原因放在寄出按鈕旁，使用者看得到是哪些附件、要怎麼處理（7-2） */}
              {result?.status === "failed" && <FailedNotice id={id} reason={result.reason} />}
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  disabled={busy || !ready || !pkg || blanks.length > 0 || recipientProblem !== ""}
                  onClick={() => withGrants("send")}
                  className={primary}
                  data-testid="submit"
                >
                  寄出
                </Button>
                <Button
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    setStep("ask");
                    writeSaved(id, null);
                  }}
                  className={secondary}
                >
                  回上一步
                </Button>
              </div>
            </section>
          )}
        </>
      )}
    </div>
  );
}

/**
 * 寄出或建立草稿失敗的說明。7 號的 reason 已寫明原因（取不到附件時列出檔名）；
 * 依 7 號的固定說法附上處理的入口：「重新上傳」連到上傳文件頁、「垃圾桶」連到 Google Drive 的垃圾桶。
 */
function FailedNotice({ id, reason }: { id: string; reason?: string | null }) {
  return (
    <div
      role="status"
      className="space-y-1 rounded-md bg-red-50 p-2 text-sm text-red-800"
      data-testid="submission"
    >
      <p>這次沒有成功，事件還沒結案。</p>
      {/* 7 號列附件時一個檔案一行（「・檔名」），照換行顯示 */}
      {reason && (
        <p className="whitespace-pre-line" data-testid="submission-reason">
          {reason}
        </p>
      )}
      {reason?.includes("垃圾桶") && (
        <p>
          <a
            href="https://drive.google.com/drive/trash"
            target="_blank"
            rel="noopener noreferrer"
            className="underline"
            data-testid="open-drive-trash"
          >
            打開 Google Drive 的垃圾桶
          </a>
          ，還原上面列出的檔案後回到這頁再按一次。
        </p>
      )}
      {reason?.includes("重新上傳") && (
        <p>
          <Link
            to="/incident/$id/documents"
            params={{ id }}
            className="underline"
            data-testid="go-upload"
          >
            到「上傳文件」重新上傳
          </Link>
          ，完成後回到這頁再按一次。
        </p>
      )}
    </div>
  );
}
