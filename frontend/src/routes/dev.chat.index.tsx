import { Button } from "@base-ui/react/button";
import { useMutation, useQuery } from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import {
  createPlanConversationMutation,
  listPlansOptions,
} from "../client/@tanstack/react-query.gen";

export const Route = createFileRoute("/dev/chat/")({
  component: ChatPlanPicker,
});

/** 開發工具：選一個固定測試方案、建立對話，再到問答測試頁提問。要先登入（可用測試登入）。 */
function ChatPlanPicker() {
  const plans = useQuery(listPlansOptions());
  const navigate = useNavigate();
  const select = useMutation({
    ...createPlanConversationMutation(),
    onSuccess: (conversation) =>
      navigate({ to: "/dev/chat/$conversationId", params: { conversationId: conversation.id } }),
  });
  const unauthorized = select.error && (select.error as { status?: number }).status === 401;

  return (
    <section className="space-y-4">
      <h2 className="text-xl font-bold">問答測試：選方案</h2>
      <p className="text-sm text-gray-600">
        選方案後建立對話並進入問答。需要登入；本機可用
        <a href="/login?next=%2Fdev%2Fchat" className="mx-1 underline">
          測試登入
        </a>
        。
      </p>
      {plans.error && (
        <p role="alert" className="text-red-600">
          無法取得方案清單，請確認條款庫已載入（make seed）。
        </p>
      )}
      {plans.isPending && !plans.error && <p>讀取中…</p>}
      <ul className="space-y-3">
        {plans.data?.map((plan) => (
          <li key={plan.id} data-testid={`plan-${plan.id}`} className="rounded-md border p-3">
            <h3 className="font-medium">{plan.name}</h3>
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
          {unauthorized ? "請先登入再建立對話。" : "建立對話失敗，請再試一次。"}
        </p>
      )}
    </section>
  );
}
