import { createFileRoute, Link } from "@tanstack/react-router";
import { getTripPackage, submitTrip } from "../client";
import { SubmitFlow, type SubmitSource } from "../features/incident/SubmitPage";
import { policyMeta, tripTitle } from "../features/incident/shared";
import { tripPending } from "../features/trip/TripTodoCards";
import { useTrip } from "../features/trip/useTrip";
import { useTripLinks } from "../features/trip/useTripLinks";

export const Route = createFileRoute("/_authed/trip/$policyId/submit")({
  component: TripSubmit,
});

/** 行程版 2-5 送件（ADR-0029）：整個行程一封信、一次送件；三種結果都結案並鎖住行程。 */
function TripSubmit() {
  const { policyId } = Route.useParams();
  const { user } = Route.useRouteContext();
  const { data: trip, refresh } = useTrip(policyId);
  const links = useTripLinks(policyId, trip);
  if (!trip) return null;
  const { missingUploads, pending } = tripPending(trip);
  const source: SubmitSource = {
    key: policyId,
    next: `/trip/${policyId}/submit`,
    meta: `${tripTitle(trip.destination, trip.policy.start_date, trip.policy.end_date)} · ${policyMeta(trip.policy.plan_name, null)}`,
    noun: "行程",
    closed: trip.locked,
    remaining: missingUploads + pending,
    missingUploads,
    ready: trip.can_submit,
    hasDocuments: [...trip.shared_documents, ...trip.incidents.flatMap((i) => i.documents)].some(
      (d) => d.storage_path,
    ),
    canSend: trip.can_send,
    loadPackage: () => getTripPackage({ path: { policy_id: policyId } }),
    submit: (body) => submitTrip({ path: { policy_id: policyId }, body }),
    refresh: async () => {
      await refresh();
    },
    links,
    back: ({ hash, className, testId, children }) => (
      <Link
        to="/trip/$policyId"
        params={{ policyId }}
        hash={hash}
        className={className}
        data-testid={testId}
      >
        {children}
      </Link>
    ),
  };
  return (
    <SubmitFlow source={source} email={user.email} googleUser={user.login_provider === "google"} />
  );
}
