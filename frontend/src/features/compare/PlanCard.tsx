import type { PlanCardOut } from "../../client/types.gen";
import { btn, wide } from "../../components/ui/buttons";
import { money, wan } from "../../lib/format";

/**
 * 方案卡（DESIGN.md 6.11）：上方置中的「推薦」／「次推薦」、公司、方案名稱、保額下拉、保費、外連按鈕。
 * 推薦卡（`highlight`）是較粗的品牌色框。使用者改過保額後，下拉標籤改成「保額（已自行調整）」。
 */
export function PlanCard({
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
  const adjusted = plan.sum_insured !== plan.recommended_sum_insured;
  const selectId = `sum-${plan.plan_code}-${label}`;
  return (
    <section
      aria-label={label}
      className={`flex flex-col gap-4 rounded-2xl bg-white p-5 shadow-card md:rounded-panel md:px-7 md:py-6 ${
        highlight ? "border-[3px] border-brand" : "border border-line"
      }`}
    >
      <p className="m-0 text-center t-caption-bold text-heading">{label}</p>
      <div>
        <p className="m-0 t-caption text-muted">{plan.company}</p>
        <h2 className="m-0 mt-0.5 t-subsection-title text-heading">{plan.name}</h2>
      </div>
      <div className="flex items-center justify-between gap-3">
        <label htmlFor={selectId} className="t-caption-bold text-heading">
          {adjusted ? "保額（已自行調整）" : "推薦保額"}
        </label>
        <select
          id={selectId}
          value={plan.sum_insured}
          disabled={disabled}
          onChange={(e) => onChange(Number(e.target.value))}
          className="min-h-10 appearance-none rounded-tag border border-line bg-white bg-[url('data:image/svg+xml,%3Csvg%20xmlns=%22http://www.w3.org/2000/svg%22%20viewBox=%220%200%2024%2024%22%20fill=%22none%22%20stroke=%22%23285442%22%20stroke-width=%222.6%22%20stroke-linecap=%22round%22%20stroke-linejoin=%22round%22%3E%3Cpath%20d=%22m6%209%206%206%206-6%22/%3E%3C/svg%3E')] bg-[length:1rem] bg-[right_0.75rem_center] bg-no-repeat py-1.5 pr-9 pl-3 t-caption-bold text-ink focus:border-brand focus:shadow-focus-input focus:outline-none disabled:bg-paper disabled:text-muted"
        >
          {plan.sum_insured_options.map((n) => (
            <option key={n} value={n}>
              {wan(n)}
              {n === plan.recommended_sum_insured && "（推薦）"}
            </option>
          ))}
        </select>
      </div>
      <p className="m-0 t-label-lg text-heading">
        {days} 天 {money(plan.premium)}
      </p>
      <a href={plan.url} target="_blank" rel="noreferrer" className={`${btn} ${wide}`}>
        前往保險公司官網投保 ↗
      </a>
    </section>
  );
}
