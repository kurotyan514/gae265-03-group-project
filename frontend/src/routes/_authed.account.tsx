import { createFileRoute, Link } from "@tanstack/react-router";

export const Route = createFileRoute("/_authed/account")({
  component: AccountPage,
});

function AccountPage() {
  const { user } = Route.useRouteContext();

  return (
    <main className="space-y-4">
      <h1 className="text-2xl font-bold">我的帳號</h1>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
        <dt className="font-medium">名稱</dt>
        <dd data-testid="account-name">{user.name ?? "（未提供）"}</dd>
        <dt className="font-medium">Email</dt>
        <dd data-testid="account-email">{user.email}</dd>
      </dl>
      {/* 登出在共用 header */}
      <Link to="/" className="inline-block rounded-md border px-3 py-1 hover:bg-gray-100">
        回首頁
      </Link>
    </main>
  );
}
