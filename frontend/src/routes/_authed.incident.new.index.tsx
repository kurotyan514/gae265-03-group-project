import { useQuery } from "@tanstack/react-query";
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { listIncidentsOptions } from "../client/@tanstack/react-query.gen";
import { btn } from "../components/ui/buttons";
import { PageHead } from "../components/ui/PageHead";
import { IncidentRow } from "../features/incident/IncidentRow";
import { PolicyStep } from "../features/incident/PolicyStep";
import { box } from "../features/incident/shared";

export const Route = createFileRoute("/_authed/incident/new/")({
  // 從 2-2 按「上一步」回來修改保單時，帶著保單編號
  validateSearch: (search: Record<string, unknown>): { policy?: string } => ({
    policy: typeof search.policy === "string" ? search.policy : undefined,
  }),
  component: CreateTripPage,
});

/**
 * 2-1 建立行程（出事了的入口）：先有一份保單（選我的保單、上傳、或手動選擇），
 * 下一步到 2-2 描述事故。畫板沒有「我的理賠」完整清單，但全部理賠頁（#208）還沒有，
 * 所以先留在頁底，旅客才找得回比首頁最近 3 筆更早的事件。
 */
function CreateTripPage() {
  const navigate = useNavigate();
  const { policy } = Route.useSearch();
  const incidents = useQuery(listIncidentsOptions());
  const [error, setError] = useState<string | null>(null);

  return (
    <main data-page-paper className="mx-auto flex max-w-[1040px] flex-col gap-6 font-ui md:px-6">
      <PageHead
        crumb="出事了：幫我處理理賠"
        title="建立行程"
        meta="填好這趟旅行的保單，之後的判斷與待辦都依這張保單產生。"
      />
      {error && (
        <p
          role="alert"
          className="m-0 rounded-btn bg-danger-soft px-4 py-2 t-caption-bold text-danger-ink"
          data-testid="error"
        >
          {error}
        </p>
      )}

      <PolicyStep
        initialPolicyId={policy}
        onError={setError}
        onNext={(policyId) => navigate({ to: "/incident/new/$policyId", params: { policyId } })}
        back={
          <Link to="/" className={btn}>
            上一步
          </Link>
        }
      />

      <section className={box} aria-label="我的理賠">
        <h2 className="t-section-title m-0 text-heading">我的理賠</h2>
        <ul className="m-0 list-none p-0" data-testid="incidents">
          {incidents.data?.length === 0 && <li className="py-4 t-body text-muted">還沒有事件</li>}
          {incidents.data?.map((i) => (
            <li key={i.id}>
              <IncidentRow incident={i} />
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
