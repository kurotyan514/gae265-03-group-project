import { Button } from "@base-ui/react/button";
import { createFileRoute, Link } from "@tanstack/react-router";
import { type FormEvent, useState } from "react";
import { getIncidentPackage, submitIncident } from "../client";
import type { ClaimPackage, SubmissionOut } from "../client/types.gen";
import { GoogleAuthResult } from "../features/google/GoogleAuthResult";
import { GoogleConsentDialog } from "../features/google/GoogleConsentDialog";
import type { GooglePurpose } from "../features/google/google";
import { useGoogleGrant } from "../features/google/useGoogleGrant";
import {
  box,
  errorText,
  input,
  primary,
  secondary,
  useIncident,
} from "../features/incident/shared";

export const Route = createFileRoute("/_authed/incident/$id/submit")({
  component: SubmitStep,
});

/** 步驟 3：預覽送件包、確認收件人後寄出。寄信用使用者的 Gmail，附件從使用者的 Drive 讀。 */
function SubmitStep() {
  const { id } = Route.useParams();
  const { user } = Route.useRouteContext();
  const { data: ctx, setIncident } = useIncident(id);
  const googleUser = user.login_provider === "google";
  const grant = useGoogleGrant(googleUser);
  const [consent, setConsent] = useState<GooglePurpose | null>(null);
  const [pkg, setPkg] = useState<ClaimPackage | null>(null);
  const [submission, setSubmission] = useState<SubmissionOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!ctx) return null;
  const todos = ctx.todos ?? [];
  const remaining = todos.filter((t) => !t.is_done && t.status !== "not_applicable").length;
  const ready = todos.length > 0 && remaining === 0;

  async function preview() {
    setBusy(true);
    setError(null);
    const res = await getIncidentPackage({ path: { incident_id: id } });
    setBusy(false);
    if (!res.data) return setError(errorText(res.error, res.response?.status));
    setPkg(res.data);
  }

  async function send(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    // 寄信要從 Drive 讀附件，再用 Gmail 寄出：缺哪個先請使用者授權
    if (googleUser) {
      if (!grant.data) return setError("正在確認 Google 授權，請稍候再按一次。");
      const missing = (["drive", "gmail"] as const).find((p) => !grant.data?.[p]);
      if (missing) return setConsent(missing);
    }
    const recipient = String(new FormData(e.currentTarget).get("recipient"));
    setBusy(true);
    setError(null);
    const res = await submitIncident({ path: { incident_id: id }, body: { recipient } });
    setBusy(false);
    if (!res.data) return setError(errorText(res.error, res.response?.status));
    setSubmission(res.data);
    const fresh = await fetch(`/api/v1/incidents/${id}`);
    if (fresh.ok) setIncident(await fresh.json());
  }

  return (
    <div className="space-y-4">
      <GoogleAuthResult />
      <GoogleConsentDialog
        purpose={consent}
        next={`/incident/${id}/submit`}
        onClose={() => setConsent(null)}
      />
      {error && (
        <p role="alert" className="rounded-md bg-red-50 p-2 text-red-800" data-testid="error">
          {error}
        </p>
      )}
      {!googleUser && (
        <p className="rounded-md bg-gray-50 p-2 text-sm text-gray-700">
          你不是用 Google 登入，沒有 Gmail 可以寄信。可以先預覽送件包，寄送請改用 Google 登入。
        </p>
      )}

      <section className={box} aria-label="送件前確認">
        <h2 className="font-bold">送件前確認</h2>
        <p className="text-sm text-gray-700" data-testid="ready">
          {ready ? (
            "所有待辦都完成了，可以送件。"
          ) : (
            <>
              還有 {remaining} 項待辦沒完成，完成後才能送件。
              <Link to="/incident/$id" params={{ id }} className="ml-1 underline">
                回到待辦
              </Link>
            </>
          )}
        </p>
        <Button
          type="button"
          onClick={preview}
          disabled={busy}
          className={secondary}
          data-testid="package"
        >
          預覽送件包
        </Button>
        {pkg && (
          <div className="space-y-1 rounded-md bg-gray-50 p-2 text-sm" data-testid="package-view">
            <p className="font-medium">{pkg.subject}</p>
            <pre className="whitespace-pre-wrap break-words">{pkg.body}</pre>
            <p>附件：{pkg.attachments?.map((a) => a.file_name).join("、") || "（無）"}</p>
          </div>
        )}
      </section>

      <section className={box} aria-label="送件">
        <h2 className="font-bold">寄給保險業務員</h2>
        <form onSubmit={send} className="flex flex-wrap gap-2">
          <input
            name="recipient"
            type="email"
            required
            defaultValue={pkg?.recipient_hint ?? ""}
            key={pkg?.recipient_hint ?? "default"}
            placeholder="業務員的 email"
            aria-label="收件人"
            className={`${input} min-w-0 flex-1`}
            data-testid="recipient"
          />
          <Button type="submit" disabled={busy || !ready} className={primary} data-testid="submit">
            送件
          </Button>
        </form>
        {submission && (
          <p
            className={submission.status === "sent" ? "text-green-800" : "text-red-700"}
            data-testid="submission"
            role="status"
          >
            {submission.status === "sent" ? "已寄出" : "寄送失敗"}
            {submission.external_ref && `（${submission.external_ref}）`}
            {submission.reason && ` ${submission.reason}`}
          </p>
        )}
      </section>
    </div>
  );
}
