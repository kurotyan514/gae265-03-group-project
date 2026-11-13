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
          <p>草稿會有協助預設填好的內容和留存在 Google Drive 的附件，你可自行修改內容後寄出。</p>
          <ul className="m-0 list-disc pl-5.5">
            <li>按下確定後，需要授權 Gmail 權限才能於你的 Gmail 建立草稿</li>
            <li>按下取消後，不需要授權但也不會於你的 Gmail 建立草稿</li>
          </ul>
          <p className="font-bold">選擇完成後，這筆理賠就會結案，之後不能再新增狀況或修改。</p>
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
