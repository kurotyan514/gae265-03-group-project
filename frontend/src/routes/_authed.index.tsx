import { createFileRoute, Link } from "@tanstack/react-router";

export const Route = createFileRoute("/_authed/")({
  component: HomePage,
});

const cardClass = "block rounded-lg border p-6 text-left";

/** 0-1 首頁：兩個入口。 */
function HomePage() {
  const { user } = Route.useRouteContext();

  return (
    <main className="space-y-6">
      <h1 className="text-2xl font-bold">{user.name ?? user.email}，你現在需要什麼？</h1>
      <div className="grid gap-4 sm:grid-cols-2">
        <Link to="/compare/new" className={`${cardClass} hover:bg-gray-100`}>
          <span className="block text-xl font-bold">出發前：幫我選方案</span>
          <span className="mt-2 block text-gray-600">依旅程與在意的點推薦方案</span>
        </Link>
        <Link to="/incident/new" className={`${cardClass} hover:bg-gray-100`}>
          <span className="block text-xl font-bold">出事了：幫我處理理賠</span>
          <span className="mt-2 block text-gray-600">整理可能適用的項目與待辦</span>
        </Link>
      </div>
      {import.meta.env.DEV && (
        <p>
          <Link to="/dev" className="text-blue-700 underline">
            開發工具（API 測試台、條文瀏覽、健康狀態）
          </Link>
        </p>
      )}
    </main>
  );
}
