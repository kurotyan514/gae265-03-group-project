import { useQuery } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import { authConfigOptions } from "../client/@tanstack/react-query.gen";
import { UserIcon } from "../components/icons";
import { btn } from "../components/ui/buttons";
import { PageHead } from "../components/ui/PageHead";
import { GoogleGrantPanel } from "../features/google/GoogleGrantPanel";

export const Route = createFileRoute("/_authed/account")({
  component: AccountPage,
});

/** 我的帳號：基本資料卡，加上 Google 授權卡（只有 Google 登入的帳號有）。 */
function AccountPage() {
  const { user } = Route.useRouteContext();
  const { data: config } = useQuery(authConfigOptions());

  return (
    <main data-page-paper className="-mx-2 space-y-6 py-4 font-ui md:mx-0 md:p-6">
      <PageHead title="我的帳號" />
      <section
        aria-labelledby="account-profile"
        className="rounded-2xl border border-line/60 bg-white px-3 pt-4 pb-4 shadow-card md:rounded-3xl md:px-4 md:pt-5 md:pb-5"
      >
        <div className="flex items-center gap-2.5 border-b border-line pt-1 pb-3.5 pl-1 md:gap-3.5 md:pt-0 md:pb-[18px] md:pl-2">
          <UserIcon className="size-7 flex-none text-leaf md:size-9" />
          <h2
            id="account-profile"
            className="text-xl font-bold leading-[30px] text-heading md:text-2xl md:leading-9"
          >
            基本資料
          </h2>
        </div>
        <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-6 gap-y-3 px-1 pt-4 md:px-2">
          <dt className="t-label text-muted">名稱</dt>
          <dd className="m-0 t-body text-ink" data-testid="account-name">
            {user.name ?? "（未提供）"}
          </dd>
          <dt className="t-label text-muted">Email</dt>
          <dd className="m-0 t-body break-all text-ink" data-testid="account-email">
            {user.email}
          </dd>
        </dl>
      </section>
      {/* 只有用 Google 登入的帳號能授權 Drive 與 Gmail */}
      {config?.google_login && user.login_provider === "google" && (
        <GoogleGrantPanel next="/account" />
      )}
      {/* 登出在共用 header */}
      <Link to="/" className={btn}>
        回首頁
      </Link>
    </main>
  );
}
