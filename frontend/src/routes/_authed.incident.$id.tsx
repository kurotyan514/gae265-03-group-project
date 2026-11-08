import { createFileRoute, Link, Outlet, useRouterState } from "@tanstack/react-router";
import { useIncident } from "../features/incident/shared";

export const Route = createFileRoute("/_authed/incident/$id")({
  component: IncidentLayout,
});

const tab = "rounded-md border px-3 py-1 hover:bg-gray-100";
const active = "rounded-md border border-gray-900 bg-gray-900 px-3 py-1 text-white";

/** 事件的共用外框：標題、狀態與三個步驟（對話與待辦、上傳文件、送件）。 */
function IncidentLayout() {
  const { id } = Route.useParams();
  const { data: ctx, error, isPending } = useIncident(id);
  const pathname = useRouterState({ select: (state) => state.location.pathname });

  if (isPending) return <p>載入中…</p>;
  if (error || !ctx) {
    return (
      <p role="alert" className="text-red-700">
        找不到這個事件。
        <Link to="/incident/new" className="underline">
          回到理賠入口
        </Link>
      </p>
    );
  }
  // 2-2 描述事故、2-3 理賠頁、2-4 上傳理賠文件有自己的頁首；舊的標題與步驟列只留在還沒換新的送件頁
  const here = pathname.replace(/\/$/, "");
  if (here === `/incident/${id}` || here === `/incident/${id}/documents`) return <Outlet />;
  const total = ctx.todos?.length ?? 0;
  const done = ctx.todos?.filter((t) => t.is_done).length ?? 0;

  return (
    <main className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold" data-testid="incident-title">
          {ctx.title}
        </h1>
        <p className="text-sm text-gray-600">
          {ctx.incident_type_name ?? "類型確認中"} ·{" "}
          {ctx.status === "completed" ? "已完成" : "進行中"}
          {" · "}
          {ctx.policy.plan_name}
          {ctx.policy.sum_insured != null &&
            ` · 保額 ${ctx.policy.sum_insured.toLocaleString()} 元`}
          {total > 0 && ` · 待辦 ${done}/${total}`}
        </p>
      </div>
      <nav aria-label="理賠步驟" className="flex flex-wrap gap-2">
        <Link
          to="/incident/$id"
          params={{ id }}
          activeOptions={{ exact: true }}
          className={tab}
          activeProps={{ className: active }}
        >
          1. 說明與待辦
        </Link>
        <Link
          to="/incident/$id/documents"
          params={{ id }}
          className={tab}
          activeProps={{ className: active }}
        >
          2. 上傳文件
        </Link>
        <Link
          to="/incident/$id/submit"
          params={{ id }}
          className={tab}
          activeProps={{ className: active }}
        >
          3. 送件
        </Link>
      </nav>
      {ctx.status === "completed" && (
        <p className="rounded-md bg-gray-100 p-2 text-sm text-gray-700" data-testid="closed-banner">
          這個事件已結案，不能再新增狀況或修改。
        </p>
      )}
      <Outlet />
    </main>
  );
}
