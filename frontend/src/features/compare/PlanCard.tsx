import type { PlanCardOut } from "../../client/types.gen";
import { btn, wide } from "../../components/ui/buttons";
import { fieldInput } from "../../components/ui/Field";
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
      className={`flex flex-col gap-4 rounded-2xl bg-white p-5 shadow-card md:rounded-panel md:p-7 ${
        highlight ? "border-[3px] border-brand" : "border border-line"
      }`}
    >
      <span className="mx-auto rounded-chip bg-leaf-soft px-3 py-0.5 t-caption-bold text-brand">
        {label}
      </span>
      <div className="text-center">
        <p className="m-0 t-caption text-muted">{plan.company}</p>
        <h2 className="m-0 mt-0.5 t-section-title text-heading">{plan.name}</h2>
      </div>
      <div className="flex flex-col gap-2">
        <label htmlFor={selectId} className="t-label text-heading">
          {adjusted ? "保額（已自行調整）" : "推薦保額"}
        </label>
        <select
          id={selectId}
          value={plan.sum_insured}
          disabled={disabled}
          onChange={(e) => onChange(Number(e.target.value))}
          className={`${fieldInput} w-full`}
        >
          {plan.sum_insured_options.map((n) => (
            <option key={n} value={n}>
              {wan(n)}
              {n === plan.recommended_sum_insured && "（推薦）"}
            </option>
          ))}
        </select>
      </div>
      <p className="m-0 text-center t-section-title text-heading">
        {days} 天 {money(plan.premium)}
      </p>
      <a href={plan.url} target="_blank" rel="noreferrer" className={`${btn} ${wide}`}>
        前往保險公司官網投保 ↗
      </a>
    </section>
  );
}
