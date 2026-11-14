import { createFileRoute, Link } from "@tanstack/react-router";
import { TripPage } from "../features/trip/TripPage";
import { useTrip } from "../features/trip/useTrip";

export const Route = createFileRoute("/_authed/trip/$policyId")({
  component: TripRoute,
});

/** 行程頁（ADR-0029）：網址 `/trip/$policyId`，行程 ＝ 保單。只有至少有一個事故的保單才有行程頁。 */
function TripRoute() {
  const { policyId } = Route.useParams();
  const { user } = Route.useRouteContext();
  const { data: trip, error, isPending } = useTrip(policyId);

  if (isPending) return <p className="font-ui">載入中…</p>;
  if (error || !trip) {
    return (
      <p role="alert" className="font-ui text-danger">
        找不到這個行程。
        <Link to="/" className="underline">
          回首頁
        </Link>
      </p>
    );
  }
  return <TripPage policyId={policyId} trip={trip} googleUser={user.login_provider === "google"} />;
}
