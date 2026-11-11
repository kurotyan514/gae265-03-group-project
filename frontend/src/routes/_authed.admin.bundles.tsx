import { createFileRoute, Link } from "@tanstack/react-router";
import { BundlesPage } from "../features/ingest/BundlesPage";

export const Route = createFileRoute("/_authed/admin/bundles")({
  component: AdminBundles,
});

/** 後台：合訂本拆分清單。需要登入（外框 _authed 負責）。 */
function AdminBundles() {
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline gap-4">
        <h1 className="text-xl font-bold">後台：合訂本拆分</h1>
        <Link to="/admin/ingest" className="text-sm underline">
          單一險種上傳
        </Link>
        <Link to="/admin/rules" className="text-sm underline">
          條文維護
        </Link>
        <Link to="/admin/excluded" className="text-sm underline">
          已不收錄
        </Link>
      </div>
      <BundlesPage />
    </div>
  );
}
