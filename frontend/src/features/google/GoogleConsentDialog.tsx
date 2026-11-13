import { btn, btnPri } from "../../components/ui/buttons";
import { Dialog, DialogShell } from "../../components/ui/DialogShell";
import { type GooglePurpose, googleAuthorizeUrl } from "./google";

type Consent = { title: string; uses: string[]; never: string[] };

// 導向 Google 授權之前，先說明這個權限拿來做什麼、不會做什麼（ADR-0020）。
const CONSENT: Record<GooglePurpose, Consent> = {
  drive: {
    title: "存放理賠文件到你的 Google Drive",
    uses: [
      "把你上傳的理賠文件存進你 Google Drive 裡的「好險有你 理賠文件」資料夾",
      "送件時從這個資料夾讀出文件，當作信件的附件",
    ],
    never: ["只能存取這個網站自己存進去的檔案，看不到你 Drive 裡的其他檔案"],
  },
  gmail: {
    title: "用你的 Gmail 寄出送件信",
    uses: ["依你確認過的預覽信件內容，替你寄出給保險公司，並留存信件紀錄於你的 Gmail 寄件備份"],
    never: ["不會讀你的信件", "不會在你沒有確認的情況下寄信"],
  },
};

/** Gmail 權限用來建立草稿時（送件頁「我自己處理就好」→ 確定）的說明。 */
const GMAIL_DRAFT: Consent = {
  title: "用你的 Gmail 建立草稿",
  uses: [
    "會為你建立 Gmail 草稿，草稿裡會有預設填好的信件內容，並附上存在 Google Drive 的附件，你可自行修改內容後寄出",
  ],
  never: ["不會讀你的信件", "不會在你沒有確認的情況下建立草稿"],
};

type Props = {
  /** 要授權的目的；null 代表對話框關著。 */
  purpose: GooglePurpose | null;
  /** 授權完要回到的站內頁面，通常是目前這一頁。 */
  next: string;
  onClose: () => void;
  /** Gmail 權限拿來做什麼：寄出（預設）或建立草稿，說明的文字不同。 */
  gmailUse?: "send" | "draft";
  /**
   * 開發頁用的模擬授權：有給的話，「同意」不前往 Google，改成呼叫它（e2e 不連 Google，ADR-0020）。
   * 正式頁面不要給。
   */
  onSimulatedGrant?: (purpose: GooglePurpose) => void;
};

/**
 * 授權前的用途說明（DESIGN.md 7.13「Google Drive 授權」「Gmail 授權」）。
 * 按「同意並前往 Google」才整頁導向授權；按「先不要」什麼都不發生。
 */
export function GoogleConsentDialog({
  purpose,
  next,
  onClose,
  gmailUse = "send",
  onSimulatedGrant,
}: Props) {
  const consent =
    purpose === "gmail" && gmailUse === "draft" ? GMAIL_DRAFT : purpose ? CONSENT[purpose] : null;
  return (
    <DialogShell
      open={purpose !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      testId="google-consent"
      title={consent?.title ?? ""}
      description={
        purpose &&
        consent && (
          <>
            <p>接下來會前往 Google，請你同意讓「好險有你」：</p>
            <ul className="m-0 list-disc pl-5.5">
              {consent.uses.map((text) => (
                <li key={text}>{text}</li>
              ))}
            </ul>
            <p>我們不會：</p>
            <ul className="m-0 list-disc pl-5.5">
              {consent.never.map((text) => (
                <li key={text}>{text}</li>
              ))}
            </ul>
            <p className="t-caption text-muted">
              Google 可能會顯示「Google 尚未驗證這個應用程式」，這是網站還在測試階段的正常情況。
              你隨時可以在「我的帳號」取消授權。
            </p>
          </>
        )
      }
      actions={
        purpose && (
          <>
            <Dialog.Close className={btn} data-testid="google-consent-cancel">
              先不要
            </Dialog.Close>
            {onSimulatedGrant ? (
              <button
                type="button"
                onClick={() => onSimulatedGrant(purpose)}
                className={btnPri}
                data-testid="google-consent-continue"
              >
                同意（模擬授權，不會前往 Google）
              </button>
            ) : (
              // 一般連結：整頁導向後端，再由後端導向 Google
              <a
                href={googleAuthorizeUrl(purpose, next)}
                className={btnPri}
                data-testid="google-consent-continue"
              >
                同意並前往 Google
              </a>
            )}
          </>
        )
      }
    />
  );
}
