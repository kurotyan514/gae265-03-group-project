import { useMutation, useQuery } from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import {
  getComparisonOptions,
  updateComparisonMutation,
} from "../client/@tanstack/react-query.gen";
import { BackgroundForm } from "../features/compare/BackgroundForm";

export const Route = createFileRoute("/_authed/compare/$id/background")({
  component: BackgroundPage,
});

/** 1-1 修改已存的比較紀錄：進來時讀回，按「下一步」存檔後到 1-2。 */
function BackgroundPage() {
  const { id } = Route.useParams();
  const path = { comparison_id: id };
  const navigate = useNavigate();
  const comparison = useQuery(getComparisonOptions({ path }));
  const update = useMutation({
    ...updateComparisonMutation(),
    onSuccess: () => {
      void navigate({ to: "/compare/$id/concerns", params: { id } });
    },
  });

  if (comparison.error) {
    return (
      <p role="alert" className="text-red-600">
        找不到這筆比較紀錄。
      </p>
    );
  }
  // 表單只用讀回的值初始化一次：等這次進頁面的讀取完成，不拿快取裡可能過期的資料
  if (!comparison.isFetchedAfterMount || !comparison.data) return <p>讀取中…</p>;
  return (
    <BackgroundForm
      initial={comparison.data}
      onSubmit={(body) => update.mutate({ path, body })}
      pending={update.isPending}
      error={update.error}
    />
  );
}
