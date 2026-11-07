import { Button } from "@base-ui/react/button";
import { useMutation } from "@tanstack/react-query";
import { createFileRoute, Link, Navigate } from "@tanstack/react-router";
import { useState } from "react";
import { updateComparisonMutation } from "../client/@tanstack/react-query.gen";
import type {
  BenefitAmountOut,
  ComparisonOut,
  ComparisonTableRowOut,
  PlanCardOut,
  RecommendationOut,
} from "../client/types.gen";
import { tripDays } from "../features/compare/BackgroundForm";
import { TermDialog } from "../features/compare/TermDialog";
import { WithComparison } from "../features/compare/WithComparison";
import { wan } from "../lib/format";

export const Route = createFileRoute("/_authed/compare/$id/result")({
  component: ResultPage,
});

const buttonClass = "rounded-md border px-3 py-1 hover:bg-gray-100 data-[disabled]:opacity-50";
const linkClass = "text-blue-700 underline";

const money = (n: number) => `${n.toLocaleString("zh-TW")} 元`;
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

  const [showBasis, setShowBasis] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [openRow, setOpenRow] = useState<ComparisonTableRowOut | null>(null);
  const rows = showAll ? rec.table : rec.table.filter((r) => r.concern || r.key === "death");

  return (
    <main className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold">推薦方案</h1>
        <p className="text-gray-600">
          {comparison.destination} ・ {tripRange(comparison.depart_date, comparison.return_date)} ・{" "}
          {days} 天 ・ {comparison.age} 歲
        </p>
      </header>

      <div className="grid gap-4 sm:grid-cols-2">
        {(["recommended", "alternative"] as const).map((card) => (
          <PlanCard
            key={card}
            label={CARD_LABEL[card]}
            highlight={card === "recommended"}
            plan={rec[card]}
            days={days}
            disabled={update.isPending}
            onChange={(sum) => changeSum(card, sum)}
          />
        ))}
      </div>
      {update.error != null && (
        <p role="alert" className="text-red-600">
          保額存檔失敗，請再試一次。
        </p>
      )}

      <section className="space-y-2 rounded-lg border border-blue-300 bg-blue-50 p-4">
        <p data-testid="reason">{rec.reason}</p>
        <Button
          aria-expanded={showBasis}
          onClick={() => setShowBasis(!showBasis)}
          className={linkClass}
        >
          {showBasis ? "收合推薦依據" : "看推薦依據"}
        </Button>
        {showBasis && (
          <ol className="list-decimal space-y-1 pl-5" data-testid="basis">
            {rec.basis.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ol>
        )}
      </section>

      <section className="space-y-2">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[32rem] border-collapse text-sm">
            <thead>
              <tr className="border-b text-left">
                <th className="p-2">保障項目</th>
                {(["recommended", "alternative"] as const).map((card) => (
                  <th key={card} className="p-2">
                    {CARD_LABEL[card]}｜{rec[card].name}・{wan(rec[card].sum_insured)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={row.key}
                  className={`border-b align-top ${row.concern ? "bg-blue-50" : ""}`}
                >
                  <th scope="row" className="p-2 text-left font-normal">
                    <Button className={linkClass} onClick={() => setOpenRow(row)}>
                      {row.label}
                    </Button>
                    {row.concern && (
                      <span className="ml-1 rounded bg-amber-100 px-1 text-xs text-amber-800">
                        你在意
                      </span>
                    )}
                  </th>
                  <td className="p-2">
                    <Benefits items={row.recommended} />
                  </td>
                  <td className="p-2">
                    <Benefits items={row.alternative} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Button aria-expanded={showAll} onClick={() => setShowAll(!showAll)} className={linkClass}>
          {showAll ? "收合" : "看全部項目"}
        </Button>
        <p className="text-sm text-gray-600">
          僅供比較參考，非投保建議。保費為易安網原始報價，正式投保以保險公司核保與條款為準；未列的保障不等於沒有保障，額度也不是保證的理賠上限。
        </p>
      </section>

      <div className="flex gap-2">
        <Link to="/compare/$id/concerns" params={{ id }} className={buttonClass}>
          上一步
        </Link>
        <Link to="/compare/$id/scenarios" params={{ id }} className={buttonClass}>
          情境試算與問答
        </Link>
        <Link to="/" className={buttonClass}>
          完成
        </Link>
      </div>

      <TermDialog
        term={
          openRow && {
            title: openRow.label,
            explanation: openRow.explanation,
            details: (["recommended", "alternative"] as const).map((card) => (
              <div key={card} className="text-sm">
                <p className="font-bold">
                  {CARD_LABEL[card]}｜{rec[card].name}
                </p>
                <Benefits items={openRow[card]} />
              </div>
            )),
          }
        }
        onClose={() => setOpenRow(null)}
      />
    </main>
  );
}

function PlanCard({
  label,
  highlight,
  plan,
  days,
  disabled,
  onChange,
}: {
  label: string;
  highlight: boolean;
  plan: PlanCardOut;
  days: number;
  disabled: boolean;
  onChange: (sum: number) => void;
}) {
  return (
    <section
      aria-label={label}
      className={`space-y-2 rounded-lg border p-4 ${highlight ? "border-2 border-blue-600" : ""}`}
    >
      <span className="rounded bg-blue-600 px-2 py-0.5 text-sm text-white">{label}</span>
      <h2 className="text-lg font-bold">{plan.name}</h2>
      <p className="text-gray-600">{plan.company}</p>
      <label className="block">
        保額{" "}
        <select
          value={plan.sum_insured}
          disabled={disabled}
          onChange={(e) => onChange(Number(e.target.value))}
          className="rounded-md border px-2 py-1"
        >
          {plan.sum_insured_options.map((n) => (
            <option key={n} value={n}>
              {wan(n)}
              {n === plan.recommended_sum_insured && "（推薦）"}
            </option>
          ))}
        </select>
      </label>
      <p className="text-sm text-gray-600">推薦保額 {wan(plan.recommended_sum_insured)}</p>
      <p className="text-xl font-bold">
        {money(plan.premium)}／{days} 天
      </p>
      <a href={plan.url} target="_blank" rel="noreferrer" className={linkClass}>
        前往易安網投保 ↗
      </a>
    </section>
  );
}

function Benefits({ items }: { items: BenefitAmountOut[] }) {
  if (items.length === 0) return <span className="text-gray-500">未列</span>;
  return (
    <ul>
      {items.map((b) => (
        <li key={b.name}>
          {b.name}：{money(b.amount)}
        </li>
      ))}
    </ul>
  );
}
