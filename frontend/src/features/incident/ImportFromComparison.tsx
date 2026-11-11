import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { listComparisonsOptions } from "../../client/@tanstack/react-query.gen";
import type { PastComparisonOut, PastPlanOut } from "../../client/types.gen";
import { btnSm } from "../../components/ui/buttons";
import { Dialog, DialogShell, PickRow } from "../../components/ui/DialogShell";

/** 帶入表單的內容：方案、保額，加上那次比較的目的地與旅遊期間。 */
export type ImportedTrip = {
  planId: string;
  sumInsured: number;
  destination: string;
  startDate: string;
  endDate: string;
};

export const IMPORT_HINT = "已帶入之前比較的資料，請依實際購買的保單確認方案、保額及保險期間。";

const dateText = (iso: string) => iso.replace(/-/g, "/");
/** 保額以「萬」顯示（設計稿 v3.7）。 */
const sumText = (n: number) => `${(n / 10000).toLocaleString()} 萬`;

function PlaneIcon() {
  return (
    <span
      aria-hidden="true"
      className="flex size-13 shrink-0 items-center justify-center rounded-full bg-leaf-soft text-leaf-text"
    >
      <svg viewBox="0 0 24 24" className="size-6" fill="currentColor" aria-hidden="true">
        <path d="M21 16v-2l-8-5V3.5a1.5 1.5 0 0 0-3 0V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5z" />
      </svg>
    </span>
  );
}

/**
 * 【從過去的比較帶入】：底部抽屜，列出最近推薦過的比較，選一次比較後再選推薦或次推薦方案。
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
        className={`${btnSm} self-start`}
        onClick={() => setOpen(true)}
        data-testid="import-from-comparison"
      >
        從過去的比較帶入
      </button>
      <DialogShell
        open={open}
        onOpenChange={(next) => {
          if (!next) close();
        }}
        variant="wide"
        testId="import-dialog"
        title={chosen === null ? "從過去的比較帶入" : "帶入哪一個方案？"}
        actions={
          chosen === null ? (
            <Dialog.Close className={btnSm}>取消</Dialog.Close>
          ) : (
            <button type="button" className={btnSm} onClick={() => setChosen(null)}>
              返回
            </button>
          )
        }
      >
        {chosen === null ? (
          <ul className="m-0 flex list-none flex-col p-0">
            {list.map((c) => (
              <li key={c.id} className="border-b border-line last:border-b-0">
                <button
                  type="button"
                  onClick={() => setChosen(c)}
                  data-testid="import-comparison"
                  className="flex w-full items-center gap-4 rounded-chip bg-white px-1 py-4 text-left hover:bg-leaf-soft/40 focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-leaf"
                >
                  <PlaneIcon />
                  <span className="min-w-0 flex-1">
                    <span className="block t-label-lg text-heading">
                      {c.destination} ・ {dateText(c.depart_date)} ・ {c.days} 天
                    </span>
                    <span className="block t-body text-muted">
                      推薦 {c.recommended.name} ・ {sumText(c.recommended.sum_insured)}
                    </span>
                  </span>
                  <span
                    aria-hidden="true"
                    className="flex size-7 shrink-0 items-center justify-center rounded-full bg-leaf-soft text-leaf-text"
                  >
                    ›
                  </span>
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <div className="flex flex-col gap-2">
            {(
              [
                ["推薦", chosen.recommended, "import-plan-recommended"],
                ["次推薦", chosen.alternative, "import-plan-alternative"],
              ] as const
            ).map(([label, plan, testId]) => (
              <PickRow key={testId} onClick={() => pick(chosen, plan)} data-testid={testId}>
                <span className="block t-label-lg text-heading">
                  {label}｜{plan.name}
                </span>
                <span className="block t-body text-muted">{sumText(plan.sum_insured)}</span>
              </PickRow>
            ))}
          </div>
        )}
      </DialogShell>
    </>
  );
}
