import { createFileRoute, Link } from "@tanstack/react-router";
import { RulesBrowser } from "../features/rules/RulesBrowser";

export const Route = createFileRoute("/_authed/admin/rules")({
  component: AdminRules,
});

/** 後台：瀏覽條文、修改標題與內文（存檔時重新計算這一條的向量）。需要登入（外框 _authed 負責）。 */
function AdminRules() {
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline gap-4">
        <h1 className="text-xl font-bold">後台：條文維護</h1>
        <Link to="/admin/ingest" className="text-sm underline">
          單一險種上傳
        </Link>
        <Link to="/admin/bundles" className="text-sm underline">
          合訂本拆分
        </Link>
      </div>
      <RulesBrowser source="admin" editable />
    </div>
  );
}
