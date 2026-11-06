import { Button } from "@base-ui/react/button";
import { createFileRoute, Link } from "@tanstack/react-router";
import { type FormEvent, type MouseEvent, useState } from "react";
import { confirmIncidentDocument } from "../client";
import type { DocumentView } from "../client/types.gen";
import { GoogleAuthResult } from "../features/google/GoogleAuthResult";
import { GoogleConsentDialog } from "../features/google/GoogleConsentDialog";
import { useGoogleGrant } from "../features/google/useGoogleGrant";
import { box, errorText, primary, secondary, useIncident } from "../features/incident/shared";

export const Route = createFileRoute("/_authed/incident/$id/documents")({
  component: DocumentsStep,
});

const STATUS: Record<DocumentView["recognition_status"], string> = {
  pending: "等待辨識",
  recognized: "辨識通過",
  needs_review: "需要你確認",
  incomplete: "內容不完整",
  failed: "辨識失敗",
};

/** 步驟 2：上傳文件。文件存到使用者的 Google Drive，所以 Google 登入的使用者要先授權 Drive。 */
function DocumentsStep() {
  const { id } = Route.useParams();
  const { user } = Route.useRouteContext();
  const { data: ctx, setIncident } = useIncident(id);
  const googleUser = user.login_provider === "google";
  const grant = useGoogleGrant(googleUser);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [chosen, setChosen] = useState<Record<string, string>>({});

  if (!ctx) return null;
  const todos = ctx.todos ?? [];
  const open = todos.filter((t) => !t.is_done && t.status !== "not_applicable");

  /** 按「選擇檔案」：Drive 還不能用就先擋下選檔視窗，說明後請使用者授權（授權會整頁跳走，選好的檔案會不見）。 */
  const chooseFile = (e: MouseEvent<HTMLInputElement>) => {
    if (!googleUser) return;
    if (!grant.data) {
      e.preventDefault();
      setNotice("正在確認 Google 授權，請稍候再按一次。");
    } else if (!grant.data.drive) {
      e.preventDefault();
      setConsent(true);
    }
  };

  async function upload(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const response = await fetch(`/api/v1/incidents/${id}/documents`, {
        method: "POST",
        body: new FormData(form),
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) return setError(errorText(body, response.status));
      const doc = body as { file_name: string; recognition_status: string; reason?: string | null };
      setNotice(
        `${doc.file_name}：${STATUS[doc.recognition_status as DocumentView["recognition_status"]] ?? doc.recognition_status}${doc.reason ? `（${doc.reason}）` : ""}`,
      );
      form.reset();
      // 重新讀事件：6 號可能勾選了待辦
      const fresh = await fetch(`/api/v1/incidents/${id}`);
      if (fresh.ok) setIncident(await fresh.json());
    } catch {
      setError(errorText(undefined));
    } finally {
      setBusy(false);
    }
  }

  async function confirm(doc: DocumentView) {
    const todoId = chosen[doc.id];
    if (!todoId) return;
    setBusy(true);
    setError(null);
    const res = await confirmIncidentDocument({
      path: { incident_id: id, document_id: doc.id },
      body: { todo_id: todoId },
    });
    setBusy(false);
    if (!res.data) return setError(errorText(res.error, res.response?.status));
    setIncident(res.data);
  }

  return (
    <div className="space-y-4">
      <GoogleAuthResult />
      <GoogleConsentDialog
        purpose={consent ? "drive" : null}
        next={`/incident/${id}/documents`}
        onClose={() => setConsent(false)}
      />
      {error && (
        <p role="alert" className="rounded-md bg-red-50 p-2 text-red-800" data-testid="error">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="rounded-md bg-green-50 p-2 text-green-800" data-testid="notice">
          {notice}
        </p>
      )}
      {!googleUser && (
        <p className="rounded-md bg-gray-50 p-2 text-sm text-gray-700">
          你不是用 Google 登入，文件無法存到 Google Drive，之後也不能用 Gmail 寄出送件信。
        </p>
      )}

      <section className={box} aria-label="還需要的文件">
        <h2 className="font-bold">還需要準備</h2>
        {open.length === 0 ? (
          <p className="text-sm text-gray-600">所有待辦都完成了。</p>
        ) : (
          <ul className="list-disc space-y-1 pl-5 text-sm" data-testid="open-todos">
            {open.map((t) => (
              <li key={t.id}>
                {t.title}
                {t.requires_upload && "（需上傳）"}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className={box} aria-label="上傳">
        <h2 className="font-bold">上傳文件</h2>
        <form onSubmit={upload} className="flex flex-wrap items-end gap-2">
          <input
            type="file"
            name="file"
            required
            aria-label="文件"
            onClick={chooseFile}
            data-testid="doc-file"
          />
          <Button type="submit" disabled={busy} className={primary} data-testid="upload">
            上傳並辨識
          </Button>
        </form>
        <ul className="space-y-2 text-sm" data-testid="documents">
          {ctx.documents?.length === 0 && <li className="text-gray-500">還沒有上傳文件</li>}
          {ctx.documents?.map((d) => (
            <li key={d.id} className="space-y-1">
              <div>
                {d.file_name} → {STATUS[d.recognition_status]}
                {d.document_kind && `（${d.document_kind}）`}
                {d.confirmed_by_user && " · 你已確認"}
              </div>
              {d.recognition_status === "needs_review" && !d.confirmed_by_user && (
                <div className="flex flex-wrap items-center gap-2">
                  <select
                    aria-label={`${d.file_name} 對應的待辦`}
                    value={chosen[d.id] ?? ""}
                    onChange={(e) => setChosen((c) => ({ ...c, [d.id]: e.target.value }))}
                    className="rounded-md border px-2 py-1"
                  >
                    <option value="">這份文件是哪一項？</option>
                    {open.map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.title}
                      </option>
                    ))}
                  </select>
                  <Button
                    type="button"
                    disabled={busy || !chosen[d.id]}
                    onClick={() => void confirm(d)}
                    className={secondary}
                  >
                    確認
                  </Button>
                </div>
              )}
            </li>
          ))}
        </ul>
      </section>

      <p className="flex flex-wrap gap-2">
        <Link to="/incident/$id" params={{ id }} className={secondary}>
          回到待辦
        </Link>
        <Link to="/incident/$id/submit" params={{ id }} className={primary}>
          下一步：送件
        </Link>
      </p>
    </div>
  );
}
