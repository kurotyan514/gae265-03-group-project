import { btn, btnPri } from "../../components/ui/buttons";
import { DialogShell } from "../../components/ui/DialogShell";

type Props = {
  open: boolean;
  /** 確定：要在使用者的 Gmail 建立草稿。 */
  onYes: () => void;
  /** 取消：不建立草稿，事件直接結案。 */
  onNo: () => void;
  /** 按 Esc 或點旁邊關掉：還沒決定，不結案。 */
  onDismiss: () => void;
};

/**
 * 使用者選「我自己處理就好」後，問要不要幫忙在 Gmail 建立草稿。選了就結案，所以先講清楚；
 * 這一步同時就是畫板的「確認結案」對話框。
 */
export function DraftQuestionDialog({ open, onYes, onNo, onDismiss }: Props) {
  return (
    <DialogShell
      open={open}
      onOpenChange={(next) => {
        if (!next) onDismiss();
      }}
      testId="draft-question"
      title="需要幫你在 Gmail 建立草稿嗎？"
      description={
        <>
          <p>草稿會放好寫好的送件信和附件，你可以在 Gmail 修改後自己寄出。</p>
          <p className="font-bold">
            不論選確定或取消，這個事件都會結案，之後不能再新增狀況或修改。
          </p>
        </>
      }
      actions={
        <>
          <button type="button" className={btn} onClick={onNo}>
            取消
          </button>
          <button type="button" className={btnPri} onClick={onYes}>
            確定
          </button>
        </>
      }
    />
  );
}
