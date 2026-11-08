import { createFileRoute } from "@tanstack/react-router";
import { DocumentsPage } from "../features/incident/DocumentsPage";
import { useIncident } from "../features/incident/shared";

export const Route = createFileRoute("/_authed/incident/$id/documents")({
  component: DocumentsStep,
});

/** 2-4 上傳理賠文件：文件存到使用者的 Google Drive，所以 Google 登入的使用者要先授權 Drive。 */
function DocumentsStep() {
  const { id } = Route.useParams();
  const { user } = Route.useRouteContext();
  const { data: ctx } = useIncident(id);
  if (!ctx) return null;
  return <DocumentsPage id={id} ctx={ctx} googleUser={user.login_provider === "google"} />;
}
