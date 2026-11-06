import { Dialog } from "@base-ui/react/dialog";

const buttonClass = "rounded-md border px-3 py-1 hover:bg-gray-100";

type Props = {
  /** 要填的項目；空陣列代表對話框關著。 */
  items: string[];
  onClose: () => void;
};

/** 寄出前的提醒：信裡還有「（請填寫＋項目）」時，列出要填的項目（7 號的送件流程第一階段）。 */
export function MissingBlanksDialog({ items, onClose }: Props) {
  return (
    <Dialog.Root
      open={items.length > 0}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <Dialog.Portal>
        <Dialog.Backdrop className="fixed inset-0 bg-black/30" />
        <Dialog.Popup className="fixed top-1/2 left-1/2 w-[min(28rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 space-y-3 rounded-lg bg-white p-5 shadow-lg">
          <Dialog.Title className="text-lg font-bold">
            信裡還有 {items.length} 項要填寫
          </Dialog.Title>
          <Dialog.Description render={<div />} className="space-y-2 text-sm">
            <ul className="list-disc pl-5">
              {items.map((item) => (
                <li key={item} data-testid="missing-item">
                  {item}
                </li>
              ))}
            </ul>
            <p>
              有空格時不會直接寄出，會存成 Gmail 草稿；請到 Gmail 補上標色的地方，再自己按寄出。
            </p>
          </Dialog.Description>
          <div className="flex justify-end">
            <Dialog.Close className={buttonClass}>我知道了</Dialog.Close>
          </div>
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
