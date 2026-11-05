import { Button } from "@base-ui/react/button";
import { useMutation } from "@tanstack/react-query";
import { createFileRoute, Link, Outlet, redirect } from "@tanstack/react-router";
import { authMe } from "../client";
import { authLogoutMutation } from "../client/@tanstack/react-query.gen";

/**
 * 需要登入的頁面的外框（不佔網址）：進來前先問後端目前是誰，沒登入就帶著原本要去的頁面轉到登入頁。
 * 登入狀態以後端的 cookie 為準，前端不另存。
 */
export const Route = createFileRoute("/_authed")({
  beforeLoad: async ({ location }) => {
    const { data, response } = await authMe();
    if (response?.status === 401) {
      throw redirect({ to: "/login", search: { next: location.href } });
    }
    // 連不到後端或其他錯誤：不當成「未登入」，免得後端壞掉時使用者被一直丟回登入頁
    if (!data) throw new Error(`無法取得登入狀態（HTTP ${response?.status ?? "無回應"}）`);
    return { user: data };
  },
  component: AuthedLayout,
});

/** 共用 header：網站名稱連回首頁，右邊是目前使用者與登出。 */
function AuthedLayout() {
  const { user } = Route.useRouteContext();
  const logout = useMutation({
    ...authLogoutMutation(),
    // 整頁跳轉，連同前端快取的資料一起清掉
    onSuccess: () => window.location.assign("/login"),
  });

  return (
    <>
      <header className="mb-6 flex flex-wrap items-center justify-between gap-2 border-b pb-3">
        <Link to="/" className="font-bold">
          好險有你｜旅遊保險推薦與理賠陪伴
        </Link>
        <div className="flex items-center gap-2">
          <span data-testid="header-user">{user.name ?? user.email}</span>
          <Button
            onClick={() => logout.mutate({})}
            disabled={logout.isPending}
            className="rounded-md border px-3 py-1 hover:bg-gray-100 data-[disabled]:opacity-50"
          >
            登出
          </Button>
        </div>
        {logout.error && (
          <p role="alert" className="w-full text-red-600">
            登出失敗，請再試一次。
          </p>
        )}
      </header>
      <Outlet />
    </>
  );
}
