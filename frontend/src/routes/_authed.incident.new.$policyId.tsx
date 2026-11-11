import { useQuery } from "@tanstack/react-query";
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { createIncident } from "../client";
import { listPoliciesOptions } from "../client/@tanstack/react-query.gen";
import { ActionBar } from "../components/ui/ActionBar";
import { btn, lnk } from "../components/ui/buttons";
import { PageHead } from "../components/ui/PageHead";
import { DescribeChat, FIRST_QUESTION } from "../features/incident/DescribeChat";
import { errorText, policyMeta, tripTitle } from "../features/incident/shared";

export const Route = createFileRoute("/_authed/incident/new/$policyId")({
  component: DescribePage,
});

/**
 * 2-2 描述事故（建立前）：保單已經好了，事件還沒有。旅客送出第一句才建立事件並叫起 5 號，
 * 成功後換到 `/incident/$id`（取代歷史紀錄，上一頁不會回到空的對話）。
 * 目的地不用另外問：後端沒帶時用保單的目的地（#203）。
 */
function DescribePage() {
  const { policyId } = Route.useParams();
  const navigate = useNavigate();
  const policies = useQuery(listPoliciesOptions());
  const policy = policies.data?.find((p) => p.id === policyId);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function start(content: string) {
    if (!content.trim() || busy) return;
    setBusy(true);
    setError(null);
    const res = await createIncident({
      path: { policy_id: policyId },
      body: { description: content },
    });
    if (!res.data) {
      setBusy(false);
      return setError(errorText(res.error, res.response?.status));
    }
    await navigate({
      to: "/incident/$id",
      params: { id: res.data.incident.incident_id },
      replace: true,
    });
  }

  if (policies.isPending) return <p className="font-ui">載入中…</p>;
  if (!policy) {
    return (
      <main className="mx-auto flex max-w-[1040px] flex-col gap-4 font-ui md:px-6">
        <p role="alert" className="m-0 t-body text-danger">
          找不到這份保單。
        </p>
        <Link to="/incident/new" className={lnk}>
          回到建立行程
        </Link>
      </main>
    );
  }

  return (
    <main className="mx-auto flex max-w-[1040px] flex-col gap-6 font-ui md:px-6">
      <PageHead
        crumb="出事了：幫我處理理賠 · 描述事故"
        title={tripTitle(policy.destination, policy.start_date, policy.end_date)}
        meta={policyMeta(policy.plan_name, policy.sum_insured)}
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

      <div data-testid="start-form">
        <DescribeChat
          busyOverlay="正在整理理賠項目…"
          lines={[{ from: "ai", text: FIRST_QUESTION }]}
          quickReplies={[]}
          placeholder="描述發生的事"
          value={text}
          onChange={setText}
          busy={busy}
          onSend={(content) => void start(content)}
        />
      </div>

      <ActionBar>
        <Link to="/incident/new" search={{ policy: policyId }} className={btn}>
          上一步
        </Link>
        <ActionBar.Push>
          <Link to="/" className={btn}>
            回首頁
          </Link>
        </ActionBar.Push>
      </ActionBar>
    </main>
  );
}
