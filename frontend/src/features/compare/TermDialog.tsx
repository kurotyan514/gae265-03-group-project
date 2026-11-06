import { Dialog } from "@base-ui/react/dialog";
import type { ReactNode } from "react";

export type Term = { title: string; explanation: string; details?: ReactNode };

/** 名詞解釋（1-5）：名稱、白話解釋，與呼叫端給的補充內容。1-3 比較表、1-4 試算卡片共用。 */
export function TermDialog({ term, onClose }: { term: Term | null; onClose: () => void }) {
  return (
    <Dialog.Root
      open={term !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <Dialog.Portal>
        <Dialog.Backdrop className="fixed inset-0 bg-black/30" />
        <Dialog.Popup className="fixed top-1/2 left-1/2 w-[min(28rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 space-y-3 rounded-lg bg-white p-5 shadow-lg">
          {term && (
            <>
              <Dialog.Title className="text-lg font-bold">{term.title}</Dialog.Title>
              <Dialog.Description>{term.explanation}</Dialog.Description>
              {term.details}
              <div className="flex justify-end">
                <Dialog.Close className="rounded-md border px-3 py-1 hover:bg-gray-100">
                  關閉
                </Dialog.Close>
              </div>
            </>
          )}
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
