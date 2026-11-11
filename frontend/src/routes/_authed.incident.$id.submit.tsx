import { createFileRoute } from "@tanstack/react-router";
import { SubmitPage } from "../features/incident/SubmitPage";
import { useIncident } from "../features/incident/shared";

export const Route = createFileRoute("/_authed/incident/$id/submit")({
  component: SubmitStep,
});

/** 2-5 送件：先問代寄或自己處理；代寄要在預覽把空格與收件者填完才能寄出；三種結果都結案（ADR-0025）。 */
function SubmitStep() {
  const { id } = Route.useParams();
  const { user } = Route.useRouteContext();
  const { data: ctx } = useIncident(id);
  if (!ctx) return null;
  return (
    <SubmitPage
      id={id}
      ctx={ctx}
      email={user.email}
      googleUser={user.login_provider === "google"}
    />
  );
}
