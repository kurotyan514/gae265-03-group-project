import { createFileRoute, Link, Outlet } from "@tanstack/react-router";

export const Route = createFileRoute("/_authed/admin")({
  component: AdminLayout,
});

/**
 * 後台外框：只有管理者（email 在後端的 ADMIN_EMAILS 名單內）看得到內容，其他人直接輸入網址
 * 只會看到說明。真正的保護在後端（後台的 API 對非管理者回 403），這裡只是不讓人看到壞掉的頁面。
 */
function AdminLayout() {
  const { user } = Route.useRouteContext();
  if (!user.is_admin) {
    return (
      <div className="space-y-3" data-testid="admin-forbidden">
        <h1 className="text-xl font-bold">沒有權限</h1>
        <p>後台只有管理者能使用。需要的話，請聯絡管理者把你的 email 加進名單。</p>
        <Link to="/" className="underline">
          回首頁
        </Link>
      </div>
    );
  }
  return <Outlet />;
}
