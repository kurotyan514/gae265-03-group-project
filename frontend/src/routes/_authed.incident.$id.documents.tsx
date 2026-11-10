import { createFileRoute, redirect } from "@tanstack/react-router";

/**
 * 2-4 已併進 2-3（設計稿 v3.7，#274）：上傳框在理賠頁待辦上方。舊連結與 Google 授權的回跳網址
 * 仍會到這裡，導回理賠頁並捲到上傳框；網址上的查詢參數（例如 `google_auth`）照帶。
 */
export const Route = createFileRoute("/_authed/incident/$id/documents")({
  beforeLoad: ({ params, location }) => {
    throw redirect({
      to: "/incident/$id",
      params: { id: params.id },
      search: location.search,
      hash: "upload-box",
      replace: true,
    });
  },
});
