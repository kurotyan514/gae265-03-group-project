import { Button } from "@base-ui/react/button";
import { useMutation } from "@tanstack/react-query";
import { createFileRoute, Link, Outlet, redirect } from "@tanstack/react-router";
import crab from "../assets/crab.png";
import { authMe } from "../client";
import { authLogoutMutation } from "../client/@tanstack/react-query.gen";
import { UserIcon } from "../components/icons";
import { ToastProvider } from "../components/ui/Toast";

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
    <ToastProvider>
      <header className="relative isolate -mx-2 -mt-6 mb-2 before:absolute before:inset-y-0 before:left-1/2 before:-z-10 before:w-screen before:-translate-x-1/2 before:border-b before:border-line before:bg-white md:mx-0 md:mb-8">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 pt-3.5 pb-3 font-ui md:h-24 md:flex-nowrap md:gap-6 md:px-6 md:py-0">
          <Link
            to="/"
            aria-label="好險有你"
            className="inline-flex items-center gap-1 whitespace-nowrap text-[22px] leading-none font-bold tracking-[0.04em] text-brand md:gap-1.5 md:text-[28px]"
          >
            <img
              src={crab}
              alt=""
              width={52}
              height={51}
              className="h-[39px] w-10 flex-none object-contain md:h-[51px] md:w-[52px]"
            />
            <span>好險有你</span>
            <svg
              viewBox="0 0 16 26"
              aria-hidden="true"
              className="ml-0.5 h-[21px] w-[13px] flex-none md:h-[26px] md:w-4"
            >
              <g stroke="#ffba00" strokeWidth="3.2" strokeLinecap="round" fill="none">
                <path d="M3 5l9-3M3 13h10M3 21l9 3" />
              </g>
            </svg>
          </Link>
          <span className="order-5 mt-1.5 basis-full whitespace-nowrap text-sm leading-[22px] font-bold text-heading md:order-none md:mt-0 md:flex md:h-10 md:basis-auto md:items-center md:border-l md:border-line md:pl-6 md:text-lg md:leading-7">
            旅遊保險推薦與理賠陪伴
          </span>
          <div className="ml-auto flex items-center text-sm leading-[22px] font-bold text-heading md:text-lg md:leading-7">
            {user.is_admin && (
              <Link
                to="/admin/ingest"
                className="mr-4 whitespace-nowrap hover:text-brand md:mr-6"
                data-testid="admin-link"
              >
                後台
              </Link>
            )}
            <span className="flex items-center gap-1.5 md:gap-3">
              <UserIcon className="hidden size-10 flex-none text-leaf md:block" />
              <span data-testid="header-user" className="max-w-[12rem] truncate">
                {user.name ?? user.email}
              </span>
            </span>
            <Button
              onClick={() => logout.mutate({})}
              disabled={logout.isPending}
              className="ml-1 h-[22px] whitespace-nowrap border-l border-line pl-4 font-bold data-[disabled]:opacity-50 md:ml-3 md:h-10 md:pl-8"
            >
              登出
            </Button>
          </div>
        </div>
        {logout.error && (
          <p role="alert" className="w-full text-red-600">
            登出失敗，請再試一次。
          </p>
        )}
      </header>
      <Outlet />
    </ToastProvider>
  );
}
