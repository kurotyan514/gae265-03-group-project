import { Dialog } from "@base-ui/react/dialog";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { listComparisonsOptions } from "../../client/@tanstack/react-query.gen";
import type { PastComparisonOut, PastPlanOut } from "../../client/types.gen";
import { secondary } from "./shared";

/** 帶入表單的內容：方案、保額，加上那次比較的目的地與旅遊期間。 */
export type ImportedTrip = {
  planId: string;
  sumInsured: number;
  destination: string;
  startDate: string;
  endDate: string;
};

export const IMPORT_HINT = "已帶入之前比較的資料，請依實際購買的保單確認方案、保額及保險期間。";

const dateText = (iso: string) => iso.slice(5).replace("-", "/");
const sumText = (n: number) => `${n.toLocaleString()} 元`;

/**
 * 【從過去比較帶入】：列出最近推薦過的比較，選一次比較後再選推薦或次推薦方案。
 * 沒有可帶入的比較時不顯示按鈕。
 */
export function ImportFromComparison({ onPick }: { onPick: (trip: ImportedTrip) => void }) {
  const comparisons = useQuery(listComparisonsOptions());
  const [open, setOpen] = useState(false);
  const [chosen, setChosen] = useState<PastComparisonOut | null>(null);

  const list = comparisons.data ?? [];
  if (list.length === 0) return null;

  function close() {
    setOpen(false);
    setChosen(null);
  }

  function pick(c: PastComparisonOut, plan: PastPlanOut) {
    onPick({
      planId: plan.plan_id,
      sumInsured: plan.sum_insured,
      destination: c.destination,
      startDate: c.depart_date,
      endDate: c.return_date,
    });
    close();
  }

  return (
    <>
      <button
        type="button"
        className={`${secondary} self-start`}
        onClick={() => setOpen(true)}
        data-testid="import-from-comparison"
      >
        從過去比較帶入
      </button>
      <Dialog.Root
        open={open}
        onOpenChange={(next) => {
          if (!next) close();
        }}
      >
        <Dialog.Portal>
          <Dialog.Backdrop className="fixed inset-0 bg-black/30" />
          <Dialog.Popup
            className="fixed bottom-0 left-1/2 max-h-[90vh] w-[min(45rem,100vw)] -translate-x-1/2 space-y-3 overflow-auto rounded-t-2xl bg-white p-5 shadow-lg"
            data-testid="import-dialog"
          >
            {chosen === null ? (
              <>
                <Dialog.Title className="text-lg font-bold">從過去比較帶入</Dialog.Title>
                <Dialog.Description className="text-sm text-gray-600">
                  最近推薦過的比較，選一次再挑要帶入的方案。
                </Dialog.Description>
                <ul className="space-y-2">
                  {list.map((c) => (
                    <li key={c.id}>
                      <button
                        type="button"
                        className="block w-full rounded-md border p-3 text-left hover:border-gray-900"
                        onClick={() => setChosen(c)}
                        data-testid="import-comparison"
                      >
                        <span className="block font-bold">
                          {c.destination} · {dateText(c.depart_date)}–{dateText(c.return_date)} ·{" "}
                          {c.days} 天
                        </span>
                        <span className="block text-sm text-gray-600">
                          推薦 {c.recommended.name} · {sumText(c.recommended.sum_insured)}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
                <div className="flex justify-end">
                  <button type="button" className={secondary} onClick={close}>
                    取消
                  </button>
                </div>
              </>
            ) : (
              <>
                <Dialog.Title className="text-lg font-bold">帶入哪一個方案？</Dialog.Title>
                <Dialog.Description className="text-sm text-gray-600">
                  {chosen.destination} · {dateText(chosen.depart_date)}–
                  {dateText(chosen.return_date)}
                </Dialog.Description>
                {(
                  [
                    ["推薦", chosen.recommended, "import-plan-recommended"],
                    ["次推薦", chosen.alternative, "import-plan-alternative"],
                  ] as const
                ).map(([label, plan, testId]) => (
                  <button
                    key={testId}
                    type="button"
                    className="block w-full rounded-md border p-3 text-left hover:border-gray-900"
                    onClick={() => pick(chosen, plan)}
                    data-testid={testId}
                  >
                    <span className="block font-bold">
                      {label}｜{plan.name}
                    </span>
                    <span className="block text-sm text-gray-600">{sumText(plan.sum_insured)}</span>
                  </button>
                ))}
                <div className="flex justify-end">
                  <button type="button" className={secondary} onClick={() => setChosen(null)}>
                    返回
                  </button>
                </div>
              </>
            )}
          </Dialog.Popup>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  );
}
