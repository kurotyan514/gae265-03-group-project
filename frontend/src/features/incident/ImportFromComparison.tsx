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

const dateText = (iso: string) => iso.slice(5).replace("-", "/");
const sumText = (n: number) => `${n.toLocaleString()} 元`;

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
        variant="bottom"
        testId="import-dialog"
        title={chosen === null ? "從過去的比較帶入" : "帶入哪一個方案？"}
        description={
          chosen === null ? (
            <p>最近推薦過的比較，選一次再挑要帶入的方案。</p>
          ) : (
            <p>
              {chosen.destination} · {dateText(chosen.depart_date)}–{dateText(chosen.return_date)}
            </p>
          )
        }
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
          <ul className="m-0 flex list-none flex-col gap-2 p-0">
            {list.map((c) => (
              <li key={c.id}>
                <PickRow onClick={() => setChosen(c)} data-testid="import-comparison">
                  <span className="block t-label-lg text-heading">
                    {c.destination} · {dateText(c.depart_date)}–{dateText(c.return_date)} · {c.days}{" "}
                    天
                  </span>
                  <span className="block t-body text-muted">
                    推薦 {c.recommended.name} · {sumText(c.recommended.sum_insured)}
                  </span>
                </PickRow>
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
