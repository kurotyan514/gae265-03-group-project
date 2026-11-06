import { Dialog } from "@base-ui/react/dialog";
import { type GooglePurpose, googleAuthorizeUrl } from "./google";

// 導向 Google 授權之前，先說明這個權限拿來做什麼、不會做什麼（ADR-0020）。
const CONSENT: Record<GooglePurpose, { title: string; uses: string[]; never: string[] }> = {
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
    uses: ["依你確認過的內容，在你的 Gmail 建立送件信的草稿，或替你寄出"],
    never: ["不會讀你的信件", "不會在你沒有確認的情況下寄信"],
  },
};

const buttonClass = "rounded-md border px-3 py-1 hover:bg-gray-100";

type Props = {
  /** 要授權的目的；null 代表對話框關著。 */
  purpose: GooglePurpose | null;
  /** 授權完要回到的站內頁面，通常是目前這一頁。 */
  next: string;
  onClose: () => void;
  /**
   * 開發頁用的模擬授權：有給的話，「同意」不前往 Google，改成呼叫它（e2e 不連 Google，ADR-0020）。
   * 正式頁面不要給。
   */
  onSimulatedGrant?: (purpose: GooglePurpose) => void;
};

/** 授權前的用途說明。按「同意並前往 Google」才整頁導向授權；按「先不要」什麼都不發生。 */
export function GoogleConsentDialog({ purpose, next, onClose, onSimulatedGrant }: Props) {
  const consent = purpose ? CONSENT[purpose] : null;
  return (
    <Dialog.Root
      open={purpose !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <Dialog.Portal>
        <Dialog.Backdrop className="fixed inset-0 bg-black/30" />
        <Dialog.Popup
          className="fixed top-1/2 left-1/2 w-[min(28rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 space-y-3 rounded-lg bg-white p-5 shadow-lg"
          data-testid="google-consent"
        >
          {purpose && consent && (
            <>
              <Dialog.Title className="text-lg font-bold">{consent.title}</Dialog.Title>
              <Dialog.Description render={<div />} className="space-y-2 text-sm">
                <p>接下來會前往 Google，請你同意讓「好險有你」：</p>
                <ul className="list-disc pl-5">
                  {consent.uses.map((text) => (
                    <li key={text}>{text}</li>
                  ))}
                </ul>
                <p>我們不會：</p>
                <ul className="list-disc pl-5">
                  {consent.never.map((text) => (
                    <li key={text}>{text}</li>
                  ))}
                </ul>
                <p className="text-gray-600">
                  Google 可能會顯示「Google 尚未驗證這個應用程式」，這是網站還在測試階段的正常情況。
                  你隨時可以在「我的帳號」取消授權。
                </p>
              </Dialog.Description>
              <div className="flex justify-end gap-2">
                <Dialog.Close className={buttonClass} data-testid="google-consent-cancel">
                  先不要
                </Dialog.Close>
                {onSimulatedGrant ? (
                  <button
                    type="button"
                    onClick={() => onSimulatedGrant(purpose)}
                    className={`${buttonClass} bg-blue-600 text-white hover:bg-blue-700`}
                    data-testid="google-consent-continue"
                  >
                    同意（模擬授權，不會前往 Google）
                  </button>
                ) : (
                  // 一般連結：整頁導向後端，再由後端導向 Google
                  <a
                    href={googleAuthorizeUrl(purpose, next)}
                    className={`${buttonClass} bg-blue-600 text-white hover:bg-blue-700`}
                    data-testid="google-consent-continue"
                  >
                    同意並前往 Google
                  </a>
                )}
              </div>
            </>
          )}
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
