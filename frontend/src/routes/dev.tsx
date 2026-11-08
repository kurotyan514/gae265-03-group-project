import { createFileRoute, Link, Outlet } from "@tanstack/react-router";

export const Route = createFileRoute("/dev")({
  component: DevLayout,
});

const tabClass = "rounded-md border px-3 py-1 hover:bg-gray-100";
const activeClass = "bg-gray-900 text-white hover:bg-gray-900";

/** 開發用頁面的外框。正式環境的後端沒有這些端點（只在非 production 註冊），所以正式 build 只顯示說明。 */
function DevLayout() {
  if (import.meta.env.PROD) {
    return (
      <main className="space-y-2">
        <h1 className="text-2xl font-bold">開發工具</h1>
        <p>這些頁面只在開發環境提供。</p>
      </main>
    );
  }
  return (
    <main className="space-y-4">
      <h1 className="text-2xl font-bold">開發工具</h1>
      <nav className="flex flex-wrap gap-2" aria-label="開發工具">
        <Link to="/dev/console" className={tabClass} activeProps={{ className: activeClass }}>
          API 測試台
        </Link>
        <Link to="/dev/rules" className={tabClass} activeProps={{ className: activeClass }}>
          條文瀏覽
        </Link>
        <Link to="/dev/ingest" className={tabClass} activeProps={{ className: activeClass }}>
          條款上傳
        </Link>
        <Link to="/dev/incident" className={tabClass} activeProps={{ className: activeClass }}>
          事件流程
        </Link>
        <Link to="/dev/chat" className={tabClass} activeProps={{ className: activeClass }}>
          問答
        </Link>
        <Link to="/dev/document" className={tabClass} activeProps={{ className: activeClass }}>
          文件辨識
        </Link>
        <Link to="/dev/package" className={tabClass} activeProps={{ className: activeClass }}>
          打包寄送
        </Link>
        <Link to="/dev/health" className={tabClass} activeProps={{ className: activeClass }}>
          健康狀態
        </Link>
        <Link to="/dev/ui" className={tabClass} activeProps={{ className: activeClass }}>
          元件預覽
        </Link>
      </nav>
      <Outlet />
    </main>
  );
}
