import { createFileRoute } from "@tanstack/react-router";

// 1-2 選擇最在意的點在 #79；先放空頁面讓 1-1 的「下一步」有地方去
export const Route = createFileRoute("/_authed/compare/$id/concerns")({
  component: () => <h1 className="text-2xl font-bold">選擇最在意的點</h1>,
});
