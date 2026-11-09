import type { ClauseView, IncidentContext } from "../../client/types.gen";
import { FactPill } from "../../components/ui/Tag";
import { card } from "./shared";

/** 「2026-07-09T00:00:00Z」或「2026/07/09」這類值取出日期，顯示成 2026/07/09；取不到回 null。 */
export function dateOf(ctx: IncidentContext): string | null {
  const fromOccurred = ctx.occurred_at?.slice(0, 10);
  if (fromOccurred) return fromOccurred.replaceAll("-", "/");
  const fact = ctx.facts?.find((f) => f.fact_key === "date")?.value;
  return fact && /^\d{4}[/-]\d{1,2}[/-]\d{1,2}$/.test(fact) ? fact.replaceAll("-", "/") : null;
}

const GROUPS: { key: NonNullable<ClauseView["conclusion"]>; title: string; dot: string }[] = [
  { key: "applicable", title: "可能適用的理賠項目", dot: "bg-leaf" },
  { key: "excluded", title: "依條款不在保障範圍", dot: "bg-coral" },
  { key: "insufficient", title: "待確認事項", dot: "bg-sun" },
];

/** 保障名稱：有節就顯示節名（去掉「第二節」的編號，例如「班機延誤保險(定額給付-累進式)」），否則章名，整份險種是「整份」。 */
export function clauseLabel(c: ClauseView): string {
  if (c.subsection) return c.subsection.replace(/^第[^節]+節\s*/, "");
  return c.section ?? "整份";
}

function Heading({ dot, children }: { dot: string; children: string }) {
  return (
    <h4 className="m-0 mb-1.5 flex items-center gap-2 t-caption-bold text-muted">
      <span aria-hidden="true" className={`size-2 rounded-full ${dot}`} />
      {children}
    </h4>
  );
}

/**
 * 事故卡（DESIGN.md 6.23）：事故類型與日期、旅客說的話、你提供的前提（事實 Pill），
 * 以及可能適用／不在保障範圍／待確認三組，各組前面一個顏色點。
 */
export function IncidentCard({ ctx }: { ctx: IncidentContext }) {
  const date = dateOf(ctx);
  const facts = (ctx.facts ?? []).filter((f) => f.fact_key !== "event_type");
  const clauses = ctx.clauses ?? [];

  return (
    <article className={`${card} flex flex-col gap-3.5`} aria-label="事故">
      <h3 className="m-0 t-subsection-title text-heading" data-testid="incident-type">
        {ctx.incident_type_name ?? "事故"}
        {date && ` · ${date}`}
      </h3>
      <p className="m-0 t-lead">{ctx.description}</p>

      <div>
        <Heading dot="bg-line">你提供的前提</Heading>
        {facts.length === 0 ? (
          <p className="m-0 t-caption text-muted">還沒有。</p>
        ) : (
          <ul className="m-0 flex list-none flex-wrap gap-2 p-0" data-testid="facts">
            {facts.map((f) => (
              <li key={f.fact_key}>
                <FactPill>
                  {f.label}：{f.value}
                </FactPill>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="flex flex-col gap-3.5" data-testid="clauses">
        {GROUPS.map((g) => {
          const items = clauses.filter((c) => c.conclusion === g.key);
          if (items.length === 0) return null;
          return (
            <div key={g.key} data-testid={`clauses-${g.key}`}>
              <Heading dot={g.dot}>{g.title}</Heading>
              <ul className="m-0 flex list-disc flex-col gap-1.5 pl-5.5">
                {items.map((c) => (
                  <li key={`${c.insurance_code}|${c.section ?? ""}|${c.subsection ?? ""}`}>
                    <span className="t-label-lg text-heading">{clauseLabel(c)}</span>
                    {c.reason && <span className="t-body"> {c.reason}</span>}
                    <span className="block t-caption text-muted">
                      {c.insurance_code}
                      {c.amount_note && `｜${c.amount_note}`}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
        {clauses.every((c) => !c.conclusion) && clauses.length > 0 && (
          <ul className="m-0 list-disc pl-5.5 t-body">
            {clauses.map((c) => (
              <li key={`${c.insurance_code}|${c.section ?? ""}|${c.subsection ?? ""}`}>
                {c.insurance_code} {clauseLabel(c)}
                {c.reason && <span className="text-muted">（{c.reason}）</span>}
              </li>
            ))}
          </ul>
        )}
      </div>
      <p className="m-0 t-caption text-muted">以上為可能適用的項目，實際以保險公司審核為準。</p>
    </article>
  );
}
