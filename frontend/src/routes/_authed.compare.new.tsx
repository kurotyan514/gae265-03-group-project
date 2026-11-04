import { useMutation } from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { createComparisonMutation } from "../client/@tanstack/react-query.gen";
import { BackgroundForm } from "../features/compare/BackgroundForm";

export const Route = createFileRoute("/_authed/compare/new")({
  component: NewComparisonPage,
});

/** 1-1 空白表單：第一次按「下一步」才建立比較紀錄，之後到 1-2。 */
function NewComparisonPage() {
  const navigate = useNavigate();
  const create = useMutation({
    ...createComparisonMutation(),
    onSuccess: (data) => {
      void navigate({ to: "/compare/$id/concerns", params: { id: data.id } });
    },
  });

  return (
    <BackgroundForm
      onSubmit={(body) => create.mutate({ body })}
      pending={create.isPending}
      error={create.error}
    />
  );
}
