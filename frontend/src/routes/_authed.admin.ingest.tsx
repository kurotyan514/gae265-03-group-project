import { createFileRoute, Link } from "@tanstack/react-router";
import { IngestPage } from "../features/ingest/IngestPage";
import { type IngestSearch, validateIngestSearch } from "../features/ingest/search";

export const Route = createFileRoute("/_authed/admin/ingest")({
  validateSearch: validateIngestSearch,
  component: AdminIngest,
});

/** 後台：上傳單一險種條款、看進度、處理待確認條文。需要登入（外框 _authed 負責）。 */
function AdminIngest() {
  const { demo, speed } = Route.useSearch();
  const navigate = Route.useNavigate();
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline gap-4">
        <h1 className="text-xl font-bold">後台：條款上傳</h1>
        <Link to="/admin/bundles" className="text-sm underline">
          合訂本拆分
        </Link>
        <Link to="/admin/rules" className="text-sm underline">
          條文維護
        </Link>
      </div>
      <IngestPage
        demo={demo === 1}
        speed={speed}
        onToggleDemo={() =>
          navigate({
            search: (prev: IngestSearch) => ({ ...prev, demo: demo === 1 ? undefined : 1 }),
          })
        }
      />
    </div>
  );
}
