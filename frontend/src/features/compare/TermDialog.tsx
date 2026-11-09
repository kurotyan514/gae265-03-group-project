import type { ReactNode } from "react";
import { btn } from "../../components/ui/buttons";
import { Dialog, DialogShell } from "../../components/ui/DialogShell";

export type Term = { title: string; explanation: string; details?: ReactNode };

/** 名詞解釋（1-5）：名稱、白話解釋、分隔線，與呼叫端給的補充內容。1-3 比較表、1-4 試算卡片共用。 */
export function TermDialog({ term, onClose }: { term: Term | null; onClose: () => void }) {
  return (
    <DialogShell
      open={term !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={term?.title}
      description={term && <p className="m-0">{term.explanation}</p>}
      actions={<Dialog.Close className={btn}>關閉</Dialog.Close>}
    >
      <hr className="m-0 border-0 border-t border-line" />
      {term?.details && <div className="flex flex-col gap-3 t-body text-ink">{term.details}</div>}
    </DialogShell>
  );
}
