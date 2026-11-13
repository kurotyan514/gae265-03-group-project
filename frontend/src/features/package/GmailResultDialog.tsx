import { btn, btnPri } from "../../components/ui/buttons";
import { Dialog, DialogShell } from "../../components/ui/DialogShell";

type Kind = "sent" | "drafted";

/** 7 號沒給這封信的連結時（假實作等），退回 Gmail 的寄件備份或草稿匣。 */
const FOLDER_URL: Record<Kind, string> = {
  sent: "https://mail.google.com/mail/#sent",
  drafted: "https://mail.google.com/mail/#drafts",
};

const TEXT: Record<Kind, { title: string; where: string; button: string }> = {
  sent: {
    title: "已寄出",
    where: "寄出的信放在你 Gmail 的「寄件備份」：",
    button: "到 Gmail 查看寄件備份",
  },
  drafted: {
    title: "已存成 Gmail 草稿",
    where: "送件信和附件已存到你 Gmail 的「草稿」，修改後自己寄出：",
    button: "到 Gmail 查看草稿",
  },
};

/** Gmail 連結：沒有或不是 Gmail 網頁的，改用資料夾連結（後端也擋過一次）。 */
export function gmailHref(kind: Kind, url?: string | null): string {
  return url?.startsWith("https://mail.google.com/") ? url : FOLDER_URL[kind];
}

/**
 * 寄出或建立草稿成功後跳出的視窗：告訴使用者信在 Gmail 的哪裡（主旨），
 * 「到 Gmail 查看」按鈕直接打開那封信（沒有連結時打開寄件備份或草稿匣），開新分頁，送件頁留著；「關閉」關掉視窗。
 */
export function GmailResultDialog({
  kind,
  subject,
  url,
  onClose,
}: {
  kind: Kind | null;
  subject?: string | null;
  url?: string | null;
  onClose: () => void;
}) {
  const text = kind ? TEXT[kind] : null;
  return (
    <DialogShell
      open={kind !== null}
      onOpenChange={(open) => !open && onClose()}
      title={text?.title ?? ""}
      testId="gmail-result-dialog"
      description={
        kind &&
        text && (
          <>
            <p>{text.where}</p>
            {subject && (
              <p className="font-bold" data-testid="gmail-result-subject">
                主旨：{subject}
              </p>
            )}
          </>
        )
      }
      actions={
        <>
          <Dialog.Close className={btn}>關閉</Dialog.Close>
          {kind && text && (
            <a
              href={gmailHref(kind, url)}
              target="_blank"
              rel="noopener noreferrer"
              className={btnPri}
              data-testid="gmail-result-link"
            >
              {text.button}
            </a>
          )}
        </>
      }
    />
  );
}
