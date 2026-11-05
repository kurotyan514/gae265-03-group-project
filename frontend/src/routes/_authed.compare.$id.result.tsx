import { createFileRoute, Link } from "@tanstack/react-router";

// 1-3 推薦與比較表另開 ticket；先放暫時頁面讓 1-2 的「下一步」有地方去
export const Route = createFileRoute("/_authed/compare/$id/result")({
  component: () => (
    <main className="space-y-4">
      <h1 className="text-2xl font-bold">推薦準備中</h1>
      <p className="text-gray-600">你填的旅行規劃與在意事項已經存好了，推薦功能還在準備中。</p>
      <Link to="/" className="text-blue-700 underline">
        回首頁
      </Link>
    </main>
  ),
});
