import { Dialog } from "@base-ui/react/dialog";

const buttonClass = "rounded-md border px-3 py-1 hover:bg-gray-100";
const primaryClass = "rounded-md bg-blue-600 px-3 py-1 text-white hover:bg-blue-700";

type Props = {
  open: boolean;
  /** 確定：要在使用者的 Gmail 建立草稿。 */
  onYes: () => void;
  /** 取消：不建立草稿，事件直接結案。 */
  onNo: () => void;
  /** 按 Esc 或點旁邊關掉：還沒決定，不結案。 */
  onDismiss: () => void;
};

/** 使用者選「我自己處理就好」後，問要不要幫忙在 Gmail 建立草稿。選了就結案，所以先講清楚。 */
export function DraftQuestionDialog({ open, onYes, onNo, onDismiss }: Props) {
  return (
    <Dialog.Root
      open={open}
      onOpenChange={(next) => {
        if (!next) onDismiss();
      }}
    >
      <Dialog.Portal>
        <Dialog.Backdrop className="fixed inset-0 bg-black/30" />
        <Dialog.Popup
          className="fixed top-1/2 left-1/2 w-[min(28rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 space-y-3 rounded-lg bg-white p-5 shadow-lg"
          data-testid="draft-question"
        >
          <Dialog.Title className="text-lg font-bold">需要幫你在 Gmail 建立草稿嗎？</Dialog.Title>
          <Dialog.Description render={<div />} className="space-y-2 text-sm">
            <p>草稿會放好寫好的送件信和附件，你可以在 Gmail 修改後自己寄出。</p>
            <p className="font-bold">
              不論選確定或取消，這個事件都會結案，之後不能再新增狀況或修改。
            </p>
          </Dialog.Description>
          <div className="flex justify-end gap-2">
            <button type="button" className={buttonClass} onClick={onNo}>
              取消
            </button>
            <button type="button" className={primaryClass} onClick={onYes}>
              確定
            </button>
          </div>
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
