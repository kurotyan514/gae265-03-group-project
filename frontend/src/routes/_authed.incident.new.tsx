import { createFileRoute, Outlet } from "@tanstack/react-router";

/** `/incident/new/*` 的外框：2-1 建立行程是 index，2-2 描述事故是 `$policyId`。 */
export const Route = createFileRoute("/_authed/incident/new")({
  component: () => <Outlet />,
});
