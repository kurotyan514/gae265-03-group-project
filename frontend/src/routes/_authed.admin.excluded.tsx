import { createFileRoute, Link } from "@tanstack/react-router";
import { ExcludedPage } from "../features/rules/ExcludedPage";

export const Route = createFileRoute("/_authed/admin/excluded")({
  component: AdminExcluded,
});

/** 後台：不收錄區，單條或整個險種收錄回來。需要登入且是管理者（外框 `_authed.admin` 負責）。 */
function AdminExcluded() {
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline gap-4">
        <h1 className="text-xl font-bold">後台：已不收錄</h1>
        <Link to="/admin/rules" className="text-sm underline">
          條文維護
        </Link>
        <Link to="/admin/ingest" className="text-sm underline">
          單一險種上傳
        </Link>
        <Link to="/admin/bundles" className="text-sm underline">
          合訂本拆分
        </Link>
      </div>
      <ExcludedPage />
    </div>
  );
}
