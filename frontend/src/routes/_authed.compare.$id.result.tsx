import { Button } from "@base-ui/react/button";
import { useMutation } from "@tanstack/react-query";
import { createFileRoute, Link, Navigate } from "@tanstack/react-router";
import { type ReactNode, useState } from "react";
import { updateComparisonMutation } from "../client/@tanstack/react-query.gen";
import type {
  BenefitAmountOut,
  ComparisonOut,
  ComparisonTableRowOut,
  RecommendationOut,
} from "../client/types.gen";
import { ActionBar } from "../components/ui/ActionBar";
import { btn, btnPri, lnk } from "../components/ui/buttons";
import { FieldError } from "../components/ui/Field";
import { PageHead } from "../components/ui/PageHead";
import { tripDays } from "../features/compare/BackgroundForm";
import { ComparisonTable } from "../features/compare/ComparisonTable";
import { PlanCard } from "../features/compare/PlanCard";
import { ReasonCard } from "../features/compare/ReasonCard";
import { TermDialog } from "../features/compare/TermDialog";
import { WithComparison } from "../features/compare/WithComparison";
import { card as cardClass } from "../features/incident/shared";
import { money } from "../lib/format";

export const Route = createFileRoute("/_authed/compare/$id/result")({
  component: ResultPage,
});

/** 2026/07/05～07/10；回程跨年才寫年份。 */
const tripRange = (depart: string, ret: string) => {
  const end = ret.startsWith(depart.slice(0, 4)) ? ret.slice(5) : ret;
  return `${depart}～${end}`.replaceAll("-", "/");
};

/** 1-3 推薦方案與比較表：資料全部來自比較紀錄的 recommendation，前端只負責畫。 */
function ResultPage() {
  const { id } = Route.useParams();
  return (
    <WithComparison id={id}>
      {(c) =>
        c.recommendation ? (
          <Result initial={c} recommendation={c.recommendation} />
        ) : (
          // 還沒選在意事項就沒有推薦：回 1-2
          <Navigate to="/compare/$id/concerns" params={{ id }} replace />
        )
      }
    </WithComparison>
  );
}

type Card = "recommended" | "alternative";
const CARD_LABEL: Record<Card, string> = { recommended: "推薦", alternative: "次推薦" };

function Result({
  initial,
  recommendation,
}: {
  initial: ComparisonOut;
  recommendation: RecommendationOut;
}) {
  const { id } = Route.useParams();
  const [comparison, setComparison] = useState(initial);
  const rec = comparison.recommendation ?? recommendation;
  const days = tripDays(comparison.depart_date, comparison.return_date);
  const update = useMutation({
    ...updateComparisonMutation(),
    onSuccess: setComparison,
  });
  const changeSum = (card: Card, sum: number) =>
    update.mutate({
      path: { comparison_id: id },
      body:
        card === "recommended"
          ? { recommended_sum_insured: sum }
          : { alternative_sum_insured: sum },
    });

  const [showAll, setShowAll] = useState(false);
  const [openRow, setOpenRow] = useState<ComparisonTableRowOut | null>(null);
  // 預設：你在意的列、身故、意外醫療；其餘按「看全部項目」才出現
  const rows = showAll
    ? rec.table
    : rec.table.filter((r) => r.concern || r.key === "death" || r.key === "accident_medical");

  return (
    <main data-page-paper className="mx-auto flex max-w-[1040px] flex-col gap-6 font-ui md:px-6">
      <PageHead
        crumb="出發前：幫我選方案 · 3／3"
        title="推薦方案與比較表"
        meta={`${comparison.destination} · ${tripRange(comparison.depart_date, comparison.return_date)} · ${days} 天 · ${comparison.age} 歲`}
      />

      <div className="grid gap-4 md:grid-cols-2 md:gap-6">
        {(["recommended", "alternative"] as const).map((which) => (
          <PlanCard
            key={which}
            label={CARD_LABEL[which]}
            highlight={which === "recommended"}
            plan={rec[which]}
            days={days}
            disabled={update.isPending}
            onChange={(sum) => changeSum(which, sum)}
          />
        ))}
      </div>
      {update.error != null && <FieldError>保額存檔失敗，請再試一次。</FieldError>}

      <ReasonCard reason={rec.reason} basis={rec.basis} />

      <section className="flex flex-col gap-3">
        <h2 className="m-0 t-section-title text-heading">保障比較</h2>
        <div className={`${cardClass} flex flex-col gap-4 md:px-6`}>
          <ComparisonTable
            columns={
              (["recommended", "alternative"] as const).map((c) => ({
                label: CARD_LABEL[c],
                head: (
                  <>
                    <span className="block t-micro text-leaf-text">{CARD_LABEL[c]}</span>
                    <span className="block t-caption text-muted">{rec[c].company}</span>
                    {rec[c].name}
                  </>
                ),
              })) as [{ label: string; head: ReactNode }, { label: string; head: ReactNode }]
            }
            rows={rows.map((row) => ({
              key: row.key,
              label: row.label,
              concernOrder: row.concern
                ? comparison.concerns.indexOf(row.concern) + 1 || undefined
                : undefined,
              onTerm: () => setOpenRow(row),
              cells: [
                <Benefits key="r" items={row.recommended} />,
                <Benefits key="a" items={row.alternative} />,
              ],
            }))}
          />
          <Button
            type="button"
            aria-expanded={showAll}
            onClick={() => setShowAll(!showAll)}
            className={`${lnk} w-full justify-center border-t border-line pt-3`}
          >
            {showAll ? "收合" : "看全部項目"}
          </Button>
        </div>
        <p className="m-0 t-caption text-muted">
          僅供比較參考，非投保建議。保費為易安網原始報價，正式投保以保險公司核保與條款為準；未列的保障不等於沒有保障，額度也不是保證的理賠上限。
        </p>
      </section>

      <ActionBar twoColumns>
        <Link to="/compare/$id/concerns" params={{ id }} className={btn}>
          上一步
        </Link>
        <ActionBar.Push>
          <ActionBar.Full>
            <Link to="/compare/$id/scenarios" params={{ id }} className={btnPri}>
              情境試算與問答
            </Link>
          </ActionBar.Full>
          <Link to="/" className={btn}>
            完成
          </Link>
        </ActionBar.Push>
      </ActionBar>

      <TermDialog
        term={
          openRow && {
            title: openRow.label,
            explanation: openRow.explanation,
            details: (["recommended", "alternative"] as const).map((which) => (
              <div key={which} className="flex flex-col gap-1">
                <p className="m-0 t-label text-heading">
                  {CARD_LABEL[which]}｜{rec[which].name}
                </p>
                <Benefits items={openRow[which]} />
              </div>
            )),
          }
        }
        onClose={() => setOpenRow(null)}
      />
    </main>
  );
}

function Benefits({ items }: { items: BenefitAmountOut[] }) {
  if (items.length === 0) return <span className="text-muted">未列</span>;
  return (
    <ul className="m-0 list-none space-y-1 p-0">
      {items.map((b) => (
        <li key={b.name}>
          {b.name}：{money(b.amount)}
        </li>
      ))}
    </ul>
  );
}
