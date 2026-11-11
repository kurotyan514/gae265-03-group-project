import { createFileRoute } from "@tanstack/react-router";
import { ClarifyingView } from "../features/incident/ClarifyingView";
import { useIncident } from "../features/incident/shared";
import { TripPage } from "../features/incident/TripPage";

export const Route = createFileRoute("/_authed/incident/$id/")({
  component: IncidentHome,
});

/** 還在追問時是 2-2 描述事故；問完（有事故類型）才是理賠頁（2-3）。結案的事件一律是理賠頁。 */
function IncidentHome() {
  const { id } = Route.useParams();
  const { user } = Route.useRouteContext();
  const { data: ctx } = useIncident(id);
  if (!ctx) return null;
  if (!ctx.incident_type_code && ctx.status !== "completed") {
    return <ClarifyingView id={id} ctx={ctx} />;
  }
  return <TripPage id={id} ctx={ctx} googleUser={user.login_provider === "google"} />;
}
