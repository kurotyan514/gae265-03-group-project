import { createFileRoute, Outlet, redirect } from "@tanstack/react-router";
import { authMe } from "../client";

/**
 * 需要登入的頁面的外框（不佔網址）：進來前先問後端目前是誰，沒登入就帶著原本要去的頁面轉到登入頁。
 * 登入狀態以後端的 cookie 為準，前端不另存。
 */
export const Route = createFileRoute("/_authed")({
  beforeLoad: async ({ location }) => {
    const { data, response } = await authMe();
    if (response?.status === 401) {
      throw redirect({ to: "/login", search: { next: location.href } });
    }
    // 連不到後端或其他錯誤：不當成「未登入」，免得後端壞掉時使用者被一直丟回登入頁
    if (!data) throw new Error(`無法取得登入狀態（HTTP ${response?.status ?? "無回應"}）`);
    return { user: data };
  },
  component: Outlet,
});
