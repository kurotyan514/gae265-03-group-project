import { Button } from "@base-ui/react/button";
import { useMutation, useQuery } from "@tanstack/react-query";
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import {
  createPlanConversationMutation,
  listPlansOptions,
} from "../client/@tanstack/react-query.gen";

export const Route = createFileRoute("/_authed/plans")({
  component: PlansPage,
});

/** 選保單：沒上傳保單時，選一個固定測試方案，選定後建立對話並進入問答頁。 */
function PlansPage() {
  const plans = useQuery(listPlansOptions());
  const navigate = useNavigate();
  const select = useMutation({
    ...createPlanConversationMutation(),
    onSuccess: (conversation) =>
      navigate({ to: "/chat/$conversationId", params: { conversationId: conversation.id } }),
  });

  return (
    <main className="space-y-4">
      <h1 className="text-2xl font-bold">選保單</h1>
      {plans.error && (
        <p role="alert" className="text-red-600">
          無法取得方案清單，請稍後再試。
        </p>
      )}
      {plans.isPending && !plans.error && <p>讀取中…</p>}
      <ul className="space-y-3">
        {plans.data?.map((plan) => (
          <li key={plan.id} data-testid={`plan-${plan.id}`} className="rounded-md border p-3">
            <h2 className="font-medium">{plan.name}</h2>
            <ul className="my-2 list-disc pl-5">
              {plan.insurances.map((ins) => (
                <li key={ins.code}>
                  {ins.name}（{ins.code}）
                </li>
              ))}
            </ul>
            <Button
              onClick={() => select.mutate({ path: { plan_id: plan.id } })}
              disabled={select.isPending}
              className="rounded-md border px-3 py-1 hover:bg-gray-100 data-[disabled]:opacity-50"
            >
              選這個方案
            </Button>
          </li>
        ))}
      </ul>
      {select.error && (
        <p role="alert" className="text-red-600">
          建立對話失敗，請再試一次。
        </p>
      )}
      <Link to="/" className="inline-block rounded-md border px-3 py-1 hover:bg-gray-100">
        回首頁
      </Link>
    </main>
  );
}
