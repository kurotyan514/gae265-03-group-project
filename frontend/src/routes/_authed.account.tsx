import { Button } from "@base-ui/react/button";
import { useMutation } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import { authLogoutMutation } from "../client/@tanstack/react-query.gen";

export const Route = createFileRoute("/_authed/account")({
  component: AccountPage,
});

function AccountPage() {
  const { user } = Route.useRouteContext();
  const logout = useMutation({
    ...authLogoutMutation(),
    // 整頁跳轉，連同前端快取的資料一起清掉
    onSuccess: () => window.location.assign("/login"),
  });

  return (
    <main className="space-y-4">
      <h1 className="text-2xl font-bold">我的帳號</h1>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
        <dt className="font-medium">名稱</dt>
        <dd data-testid="account-name">{user.name ?? "（未提供）"}</dd>
        <dt className="font-medium">Email</dt>
        <dd data-testid="account-email">{user.email}</dd>
      </dl>
      {logout.error && (
        <p role="alert" className="text-red-600">
          登出失敗，請再試一次。
        </p>
      )}
      <div className="flex gap-2">
        <Button
          onClick={() => logout.mutate({})}
          disabled={logout.isPending}
          className="rounded-md border px-3 py-1 hover:bg-gray-100 data-[disabled]:opacity-50"
        >
          登出
        </Button>
        <Link to="/" className="rounded-md border px-3 py-1 hover:bg-gray-100">
          回首頁
        </Link>
      </div>
    </main>
  );
}
