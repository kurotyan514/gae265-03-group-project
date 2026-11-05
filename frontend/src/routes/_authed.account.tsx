import { useQuery } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import { authConfigOptions } from "../client/@tanstack/react-query.gen";
import { GoogleGrantPanel } from "../features/google/GoogleGrantPanel";

export const Route = createFileRoute("/_authed/account")({
  component: AccountPage,
});

function AccountPage() {
  const { user } = Route.useRouteContext();
  const { data: config } = useQuery(authConfigOptions());

  return (
    <main className="space-y-4">
      <h1 className="text-2xl font-bold">我的帳號</h1>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
        <dt className="font-medium">名稱</dt>
        <dd data-testid="account-name">{user.name ?? "（未提供）"}</dd>
        <dt className="font-medium">Email</dt>
        <dd data-testid="account-email">{user.email}</dd>
      </dl>
      {/* 只有用 Google 登入的帳號能授權 Drive 與 Gmail */}
      {config?.google_login && user.login_provider === "google" && (
        <GoogleGrantPanel next="/account" />
      )}
      {/* 登出在共用 header */}
      <Link to="/" className="inline-block rounded-md border px-3 py-1 hover:bg-gray-100">
        回首頁
      </Link>
    </main>
  );
}
