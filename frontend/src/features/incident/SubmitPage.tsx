import { Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { getIncidentPackage, submitIncident } from "../../client";
import type {
  ClaimPackage,
  IncidentContext,
  SubmissionOut,
  UnavailableAttachment,
} from "../../client/types.gen";
import { ActionBar } from "../../components/ui/ActionBar";
import { btn, btnPri } from "../../components/ui/buttons";
import { Dialog, DialogShell } from "../../components/ui/DialogShell";
import { PageHead } from "../../components/ui/PageHead";
import { PlaceholderButton } from "../../components/ui/PlaceholderButton";
import { GoogleAuthResult } from "../google/GoogleAuthResult";
import { GoogleConsentDialog } from "../google/GoogleConsentDialog";
import type { GooglePurpose } from "../google/google";
import { useGoogleGrant } from "../google/useGoogleGrant";
import { fillBlanks, missingItems } from "../package/blanks";
import { ClaimLetter } from "../package/ClaimLetter";
import { DraftQuestionDialog } from "../package/DraftQuestionDialog";
import { card, errorText, policyMeta, tripTitle, useIncident } from "./shared";

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

const notice = "m-0 rounded-btn px-4 py-2 t-caption";

/**
 * 2-5 送件（DESIGN.md 7.12）：先問代寄或自己處理；代寄要在預覽把空格與收件者填完才能寄出，
 * 寄出前再確認一次；三種結果都結案（ADR-0025）。
 */
export function SubmitPage({
  id,
  ctx,
  email,
  googleUser,
}: {
  id: string;
  ctx: IncidentContext;
  email: string;
  googleUser: boolean;
}) {
  const { setIncident } = useIncident(id);
  const grant = useGoogleGrant(googleUser);
  const [saved] = useState(() => loadSaved(id));
  const [step, setStep] = useState<Step>(saved.step ?? "ask");
  const [values, setValues] = useState<Record<string, string>>(saved.values ?? {});
  const [recipient, setRecipient] = useState(saved.recipient ?? "");
  const [intent, setIntent] = useState<Intent>(saved.intent ?? "preview");
  const [consent, setConsent] = useState<GooglePurpose | null>(null);
  const [askingDraft, setAskingDraft] = useState(saved.intent === "draft");
  const [confirmingSend, setConfirmingSend] = useState(false);
  const [pkg, setPkg] = useState<ClaimPackage | null>(null);
  const [result, setResult] = useState<SubmissionOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 建立草稿時因為一定要附上的文件找不到被擋下：詢問頁顯示提示框，說明用「建立草稿」
  const [draftBlocked, setDraftBlocked] = useState(false);

  const closed = ctx.status === "completed";

  // 授權回來：原本要看預覽就直接進預覽；要寄出或建立草稿的，讓使用者再按一次確認
  useEffect(() => {
    if (saved.intent === "preview") setStep("preview");
    if (saved.intent) writeSaved(id, { ...saved, intent: undefined });
  }, [id, saved]);

  // 預覽時填的空格與收件者隨時暫存：切到「上傳文件」等其他頁再回來也接得上（#155 驗收 7-2 的回饋）。
  // 「取消」與送件成功會清掉；結案後不再存
  useEffect(() => {
    if (closed || step !== "preview") return;
    writeSaved(id, { step, values, recipient });
  }, [id, closed, step, values, recipient]);

  // 進到預覽才讀信；收件者沒填時帶入 7 號的建議
  useEffect(() => {
    if (step !== "preview" || pkg || closed) return;
    getIncidentPackage({ path: { incident_id: id } }).then((res) => {
      if (!res.data) return setError(errorText(res.error, res.response?.status));
      setPkg(res.data);
      setRecipient((current) => current || res.data?.recipient_hint || "");
    });
  }, [step, pkg, closed, id]);

  const todos = ctx.todos ?? [];
  const active = todos.filter((t) => t.applicable !== false);
  const remainingTodos = active.filter((t) => !t.is_done).length;
  const missingUploads = active.filter((t) => t.requires_upload && !t.is_done).length;
  const ready = todos.length > 0 && remainingTodos === 0;
  const hasDocuments = (ctx.documents ?? []).length > 0;

  const filled = pkg && {
    ...pkg,
    subject: fillBlanks(pkg.subject, values),
    body: fillBlanks(pkg.body, values),
  };
  const blanks = filled ? missingItems(filled.subject, filled.body) : [];
  // 7 號在 Drive 上取不到需上傳的文件時，把那項待辦列為還缺（契約 v2.8）：處理好才能寄出
  const lostRequired = (pkg?.missing_todo_ids?.length ?? 0) > 0;
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
    if (!res.data) {
      // 送件包還缺待辦（409）時，重新讀一次送件包：如果是一定要附上的文件在 Drive 上找不到，
      // 顯示和預覽頁一樣的提示框，不顯示平台籠統的訊息（例如從「我自己處理就好」建立草稿時）
      if (res.response?.status === 409 && mode !== "self") {
        const fresh = await getIncidentPackage({ path: { incident_id: id } });
        if (fresh.data?.missing_todo_ids?.length && fresh.data.unavailable_attachments?.length) {
          setPkg(fresh.data);
          setDraftBlocked(mode === "draft");
          return;
        }
      }
      return setError(errorText(res.error, res.response?.status));
    }
    setResult(res.data);
    if (res.data.status !== "failed") writeSaved(id, null);
    const fresh = await fetch(`/api/v1/incidents/${id}`);
    if (fresh.ok) setIncident(await fresh.json());
  }

  /** 重新讀送件包：使用者到垃圾桶還原或重新上傳之後按「重新檢查」。 */
  async function recheckPackage() {
    setError(null);
    const res = await getIncidentPackage({ path: { incident_id: id } });
    if (!res.data) return setError(errorText(res.error, res.response?.status));
    setPkg(res.data);
  }

  /**
   * 要做某件事之前：寄信與建草稿要用 Gmail；有上傳過文件時附件要從 Drive 讀，缺哪個先說明（先 Drive 再 Gmail）。
   * 沒上傳文件的使用者可能從沒授權 Drive，這時只問 Gmail。
   */
  function withGrants(next: Intent) {
    setIntent(next);
    if (googleUser) {
      if (!grant.data) return setError("正在確認 Google 授權，請稍候再按一次。");
      const needed = hasDocuments ? (["drive", "gmail"] as const) : (["gmail"] as const);
      const missing = needed.find((p) => !grant.data?.[p]);
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
  const meta = `${tripTitle(ctx.destination, ctx.policy.start_date, ctx.policy.end_date)} · ${policyMeta(ctx.policy.plan_name, null)}`;
  const preview = step === "preview" && !closed;

  return (
    <main data-page-paper className="mx-auto flex max-w-[1040px] flex-col gap-6 font-ui md:px-6">
      <PageHead
        crumb="出事了：幫我處理理賠"
        title={closed ? "送件結果" : preview ? "確認信件" : "送件"}
        meta={
          preview ? "請填好收件者和標色的地方，全部填完才能寄出。寄件者是你自己的 Gmail。" : meta
        }
      />
      <GoogleAuthResult grantedText="已完成 Google Gmail 授權。" />
      <GoogleConsentDialog
        purpose={consent}
        next={`/incident/${id}/submit`}
        onClose={declineGrant}
        gmailUse={intent === "draft" ? "draft" : "send"}
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
      <DialogShell
        open={confirmingSend && !closed}
        onOpenChange={(open) => !open && setConfirmingSend(false)}
        title="確定寄出？"
        description={
          <>
            <p>
              依你確認過的預覽信件內容，替你寄出給保險公司，並留存信件紀錄於你的 Gmail 寄件備份。
            </p>
            <p className="font-bold">寄出後這筆理賠即結案，之後無法再新增狀況或修改。</p>
          </>
        }
        testId="send-confirm-dialog"
        actions={
          <>
            <Dialog.Close className={btn}>取消</Dialog.Close>
            <button
              type="button"
              className={btnPri}
              data-testid="send-confirm"
              onClick={() => {
                setConfirmingSend(false);
                withGrants("send");
              }}
            >
              確定寄出
            </button>
          </>
        }
      />
      {error && (
        <p
          role="alert"
          className={`${notice} bg-danger-soft t-caption-bold text-danger-ink`}
          data-testid="error"
        >
          {error}
        </p>
      )}
      {!googleUser && !closed && (
        <p className={`${notice} bg-paper text-muted`}>
          你不是用 Google 登入，沒有 Gmail 可以寄信或建立草稿。可以先預覽信件，寄送請改用 Google
          登入。
        </p>
      )}
      {result?.status === "failed" && step !== "preview" && (
        <FailedNotice id={id} reason={result.reason} />
      )}

      {closed ? (
        <>
          <section className={`${card} flex flex-col gap-3`} aria-label="送件結果">
            <p className="m-0 t-lead text-heading" data-testid="closed">
              {closedText ?? "這個事件已結案。"}
              此事件已結案，不能再新增狀況或修改。
            </p>
            <p className="m-0 t-caption text-muted" data-testid="closed-banner">
              這筆理賠已結案，只能查看。
            </p>
            <div className="flex flex-wrap gap-3">
              <PlaceholderButton kind="small">到 Gmail 查看</PlaceholderButton>
              <PlaceholderButton kind="small">下載全部文件</PlaceholderButton>
            </div>
          </section>
          {result?.status === "sent" && filled && (
            <ClaimLetter pkg={filled} sender={email} recipient={recipient.trim()} />
          )}
          <ActionBar>
            <Link to="/incident/$id" params={{ id }} className={btn}>
              回理賠頁
            </Link>
          </ActionBar>
        </>
      ) : (
        <>
          {/* 備齊時畫面上不再多一行說明（設計稿 v3.7），留給讀屏與測試；沒備齊或有問題時才顯示 */}
          <p
            className={`m-0 t-body text-muted ${ready && !lostRequired ? "sr-only" : ""}`}
            data-testid="ready"
          >
            {ready && lostRequired ? (
              `有一定要附上的文件在 Google Drive 上找不到，處理好才能${
                step === "ask" && draftBlocked ? "建立草稿" : "送件"
              }。`
            ) : ready ? (
              "所有待辦都完成了，可以送件。"
            ) : missingUploads > 0 ? (
              <>
                需上傳的文件還沒備齊，還有 {remainingTodos} 項待辦沒完成，備齊後才能送件。
                <Link
                  to="/incident/$id"
                  params={{ id }}
                  hash="upload-box"
                  className="ml-1 underline"
                >
                  上傳文件
                </Link>
              </>
            ) : (
              <>
                還有 {remainingTodos} 項待辦沒完成，完成後才能送件。
                <Link to="/incident/$id" params={{ id }} className="ml-1 underline">
                  回到待辦
                </Link>
              </>
            )}
          </p>

          {step === "ask" &&
            draftBlocked &&
            pkg?.unavailable_attachments &&
            pkg.unavailable_attachments.length > 0 && (
              <UnavailableNotice
                id={id}
                items={pkg.unavailable_attachments}
                blocking={lostRequired}
                action="draft"
                onRecheck={() => void recheckPackage()}
              />
            )}
          {step === "ask" && (
            <section
              className={`${card} flex flex-col gap-3.5`}
              aria-label="送件方式"
              data-testid="ask"
            >
              <h2 className="m-0 t-section-title text-heading">
                要由我們用你的 Gmail 幫你寄給保險公司嗎？
              </h2>
              <p className="m-0 t-caption text-muted">
                寄件者是你的 Gmail，網站需要的 Gmail
                權限用於協助建立草稿或者用於協助寄信，僅選擇一項服務提供，確定後就會讓這筆理賠結案。
              </p>
              {/* 兩個按鈕照順序、內容寬度，放不下才換行（設計稿 v3.7 手機版不撐滿、不調順序） */}
              <ActionBar>
                <button
                  type="button"
                  disabled={busy || !ready}
                  onClick={() => setAskingDraft(true)}
                  className={btn}
                  data-testid="choose-self"
                >
                  我自己處理就好
                </button>
                <button
                  type="button"
                  disabled={busy || !ready}
                  onClick={() => withGrants("preview")}
                  className={btnPri}
                  data-testid="choose-send"
                >
                  好險有你小助理幫我送出
                </button>
              </ActionBar>
            </section>
          )}
          {step === "ask" && (
            <ActionBar>
              <Link to="/incident/$id" params={{ id }} className={btn}>
                回理賠頁
              </Link>
            </ActionBar>
          )}

          {step === "preview" && (
            <section className="flex flex-col gap-4" aria-label="預覽與寄出" data-testid="preview">
              {pkg?.unavailable_attachments && pkg.unavailable_attachments.length > 0 && (
                <UnavailableNotice
                  id={id}
                  items={pkg.unavailable_attachments}
                  blocking={lostRequired}
                  action="send"
                  onRecheck={() => void recheckPackage()}
                />
              )}
              {pkg ? (
                <ClaimLetter
                  pkg={pkg}
                  values={values}
                  onFill={(item, value) => setValues({ ...values, [item]: value })}
                  sender={email}
                  recipient={recipient}
                  onRecipient={setRecipient}
                />
              ) : (
                <p className="m-0 t-body text-muted">讀取送件信中…</p>
              )}
              {pkg && recipientProblem && (
                <p data-testid="recipient-problem" className="m-0 t-caption-bold text-danger">
                  {recipientProblem}
                </p>
              )}
              {blanks.length > 0 && (
                <p data-testid="missing" role="alert" className="m-0 t-caption-bold text-danger">
                  還有 {blanks.length} 處「（請填寫）」要填（
                  {blanks.map((item, i) => (
                    <span key={item}>
                      {i > 0 && "、"}
                      <span data-testid="missing-item">{item}</span>
                    </span>
                  ))}
                  ）。
                </p>
              )}
              {/* 寄出失敗的原因放在寄出按鈕旁，看得到是哪些附件、要怎麼處理（#155 驗收 7-2） */}
              {result?.status === "failed" && <FailedNotice id={id} reason={result.reason} />}
              {/* 取消在左、寄出在右，手機也同一列（設計稿 v3.7） */}
              <div className="flex items-center justify-between gap-3">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    setStep("ask");
                    writeSaved(id, null);
                  }}
                  className={btn}
                  data-testid="preview-cancel"
                >
                  取消
                </button>
                <button
                  type="button"
                  disabled={
                    busy ||
                    !ready ||
                    !pkg ||
                    lostRequired ||
                    blanks.length > 0 ||
                    recipientProblem !== ""
                  }
                  onClick={() => setConfirmingSend(true)}
                  className={btnPri}
                  data-testid="submit"
                >
                  寄出
                </button>
              </div>
            </section>
          )}
        </>
      )}
    </main>
  );
}

/**
 * 寄出或建立草稿失敗的說明。7 號的 reason 已寫明原因，取不到附件時是一句說明加上一個檔案一行，照換行顯示；
 * 依 7 號的固定說法附上處理的入口：「垃圾桶」連到 Google Drive 的垃圾桶、「重新上傳」連到上傳文件頁。
 */
function FailedNotice({ id, reason }: { id: string; reason?: string | null }) {
  return (
    <div
      role="status"
      className={`${notice} flex flex-col gap-1 bg-danger-soft text-danger-ink`}
      data-testid="submission"
    >
      <p className="m-0">這次沒有成功，事件還沒結案。</p>
      {reason && (
        <p className="m-0 whitespace-pre-line" data-testid="submission-reason">
          {reason}
        </p>
      )}
      {reason?.includes("垃圾桶") && (
        <p className="m-0">
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
        <p className="m-0">
          <Link
            to="/incident/$id"
            params={{ id }}
            hash="upload-box"
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

const UNAVAILABLE_REASON: Record<UnavailableAttachment["reason"], string> = {
  not_found: "已刪除",
  trashed: "在垃圾桶裡",
};

/**
 * 預覽時 7 號在 Drive 上取不到的附件（契約 v2.8）：不會附在信裡，提示使用者重新上傳或到垃圾桶還原。
 * 已經重新上傳的不會列在這裡。需上傳的文件（blocking）處理好才能寄出或建立草稿（依 action 說明）；其他的不處理也能寄出，
 * 信上寫「（另行提供）」。這些說明只在畫面上，不會出現在寄給保險公司的信裡。
 */
function UnavailableNotice({
  id,
  items,
  blocking,
  action,
  onRecheck,
}: {
  id: string;
  items: UnavailableAttachment[];
  blocking: boolean;
  /** 使用者這次要做的事：寄出（預覽頁）或建立草稿（「我自己處理就好」） */
  action: "send" | "draft";
  onRecheck: () => void;
}) {
  const trashed = items.some((item) => item.reason === "trashed");
  return (
    <div
      role="status"
      className={`${notice} flex flex-col gap-1 bg-warn-soft text-warn-ink`}
      data-testid="unavailable-attachments"
    >
      <p className="m-0 t-caption-bold">
        下面 {items.length} 個附件在 Google Drive 上找不到，不會附在信裡：
      </p>
      <ul className="m-0 list-none p-0">
        {items.map((item) => (
          <li key={item.document_id} data-testid="unavailable-attachment">
            ・{item.file_name}（{UNAVAILABLE_REASON[item.reason]}）
          </li>
        ))}
      </ul>
      <p className="m-0">
        {blocking ? "這是一定要附上的文件，" : "要附上的話，"}
        {trashed && (
          <>
            <a
              href="https://drive.google.com/drive/trash"
              target="_blank"
              rel="noopener noreferrer"
              className="underline"
              data-testid="unavailable-open-trash"
            >
              到 Google Drive 的垃圾桶還原
            </a>
            ，或
          </>
        )}
        <Link
          to="/incident/$id"
          params={{ id }}
          hash="upload-box"
          className="underline"
          data-testid="unavailable-go-upload"
        >
          到「上傳文件」重新上傳
        </Link>
        ，處理完按
        <button
          type="button"
          onClick={onRecheck}
          className="mx-1 underline"
          data-testid="unavailable-recheck"
        >
          重新檢查
        </button>
        。
        {blocking
          ? `處理好之前不能${action === "draft" ? "建立草稿" : "寄出"}。`
          : "不處理也能寄出，信上會寫「另行提供」。"}
      </p>
    </div>
  );
}
