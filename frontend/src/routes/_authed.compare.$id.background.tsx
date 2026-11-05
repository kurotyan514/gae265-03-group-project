import { useMutation } from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { updateComparisonMutation } from "../client/@tanstack/react-query.gen";
import { BackgroundForm } from "../features/compare/BackgroundForm";
import { WithComparison } from "../features/compare/WithComparison";

export const Route = createFileRoute("/_authed/compare/$id/background")({
  component: BackgroundPage,
});

/** 1-1 修改已存的比較紀錄：進來時讀回，按「下一步」存檔後到 1-2。 */
function BackgroundPage() {
  const { id } = Route.useParams();
  const path = { comparison_id: id };
  const navigate = useNavigate();
  const update = useMutation({
    ...updateComparisonMutation(),
    onSuccess: () => {
      void navigate({ to: "/compare/$id/concerns", params: { id } });
    },
  });

  return (
    <WithComparison id={id}>
      {(comparison) => (
        <BackgroundForm
          initial={comparison}
          onSubmit={(body) => update.mutate({ path, body })}
          pending={update.isPending}
          error={update.error}
        />
      )}
    </WithComparison>
  );
}
