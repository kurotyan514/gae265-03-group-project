import { createFileRoute, Link, Outlet } from "@tanstack/react-router";
import { useIncident } from "../features/incident/shared";

export const Route = createFileRoute("/_authed/incident/$id")({
  component: IncidentLayout,
});

/**
 * 事件的共用外框：只負責載入與找不到。各頁（2-2 描述事故、2-3 理賠頁、2-4 上傳理賠文件、2-5 送件）
 * 都有自己的頁首，舊的標題、步驟列與結案橫幅已經拿掉。
 */
function IncidentLayout() {
  const { id } = Route.useParams();
  const { data: ctx, error, isPending } = useIncident(id);

  if (isPending) return <p className="font-ui">載入中…</p>;
  if (error || !ctx) {
    return (
      <p role="alert" className="font-ui text-danger">
        找不到這個事件。
        <Link to="/incident/new" className="underline">
          回到理賠入口
        </Link>
      </p>
    );
  }
  return <Outlet />;
}
