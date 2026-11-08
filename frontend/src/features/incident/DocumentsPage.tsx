import { Link, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { confirmIncidentDocument } from "../../client";
import type { DocumentView, IncidentContext, TodoView } from "../../client/types.gen";
import { ActionBar } from "../../components/ui/ActionBar";
import { btn, btnPri, btnSm } from "../../components/ui/buttons";
import { FileDrop, FilePickButton } from "../../components/ui/FileDrop";
import { PageHead } from "../../components/ui/PageHead";
import { PlaceholderButton } from "../../components/ui/PlaceholderButton";
import { Pill } from "../../components/ui/Tag";
import { useToast } from "../../components/ui/Toast";
import { GoogleAuthResult } from "../google/GoogleAuthResult";
import { GoogleConsentDialog } from "../google/GoogleConsentDialog";
import { useGoogleGrant } from "../google/useGoogleGrant";
import { dateOf } from "./IncidentCard";
import { card, errorText, policyMeta, tripTitle, useIncident } from "./shared";

const STATUS: Record<DocumentView["recognition_status"], string> = {
  pending: "等待辨識",
  recognized: "辨識通過",
  needs_review: "無法辨識，需要你確認",
  incomplete: "內容不完整",
  failed: "辨識失敗",
};

/** 上傳結果的顏色（DESIGN.md 6.27）：通過品牌色、有問題警示色、其餘危險色。 */
const RESULT_TONE: Record<DocumentView["recognition_status"], string> = {
  pending: "text-muted font-bold",
  recognized: "text-brand font-bold",
  needs_review: "text-warn font-bold",
  incomplete: "text-warn font-bold",
  failed: "text-danger font-bold",
};

/** 上傳回應的訊息條（DESIGN.md 6.26）：有問題的用警示或危險底，通過的用一般文字。 */
function UploadNote({ status, children }: { status: string; children: string }) {
  const style =
    status === "recognized" || status === "pending"
      ? "text-brand"
      : status === "failed"
        ? "bg-danger-soft text-danger-ink"
        : "bg-warn-soft text-warn-ink";
  return <p className={`m-0 rounded-tag px-3 py-2 t-caption ${style}`}>{children}</p>;
}

const open = (t: TodoView) => !t.is_done && t.applicable !== false;

/**
 * 2-4 上傳理賠文件（DESIGN.md 7.11）：還缺的文件、檔案拖放區、辨識結果。
 * 文件存到使用者的 Google Drive，所以 Google 登入的使用者要先授權 Drive；選好檔案就直接上傳辨識。
 */
export function DocumentsPage({
  id,
  ctx,
  googleUser,
}: {
  id: string;
  ctx: IncidentContext;
  googleUser: boolean;
}) {
  const { setIncident } = useIncident(id);
  const grant = useGoogleGrant(googleUser);
  const toast = useToast();
  const navigate = useNavigate();
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notices, setNotices] = useState<{ status: string; text: string }[]>([]);
  const [chosen, setChosen] = useState<Record<string, string>>({});

  const todos = ctx.todos ?? [];
  // 結案後鎖住：後端會回 409，畫面直接停用（#152）
  const closed = ctx.status === "completed";
  const missing = todos.filter((t) => t.requires_upload && open(t));
  const openTodos = todos.filter(open);
  const documents = ctx.documents ?? [];
  const date = dateOf(ctx);
  const driveReady = !googleUser || grant.data?.drive === true;

  async function upload(files: File[]) {
    setBusy(true);
    setError(null);
    setNotices([]);
    const results: { status: string; text: string }[] = [];
    try {
      for (const file of files) {
        const body = new FormData();
        body.append("file", file);
        const response = await fetch(`/api/v1/incidents/${id}/documents`, { method: "POST", body });
        const data = await response.json().catch(() => null);
        if (!response.ok) {
          setError(errorText(data, response.status));
          break;
        }
        const doc = data as {
          file_name: string;
          recognition_status: DocumentView["recognition_status"];
          reason?: string | null;
        };
        results.push({
          status: doc.recognition_status,
          text: `${doc.file_name}：${STATUS[doc.recognition_status] ?? doc.recognition_status}${doc.reason ? `（${doc.reason}）` : ""}`,
        });
      }
      setNotices(results);
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

  // 還缺的文件依「這個事故」與「整個行程」分組
  const groups = [
    {
      title: `${ctx.incident_type_name ?? "這次事故"}${date ? ` · ${date}` : ""}`,
      items: missing.filter((t) => t.scope !== "policy"),
    },
    { title: "整個行程", items: missing.filter((t) => t.scope === "policy") },
  ].filter((g) => g.items.length > 0);

  return (
    <main className="mx-auto flex max-w-[1040px] flex-col gap-6 font-ui md:px-6">
      <PageHead
        crumb="出事了：幫我處理理賠"
        title="上傳理賠文件"
        meta={`${tripTitle(ctx.destination, ctx.policy.start_date, ctx.policy.end_date)} · ${policyMeta(ctx.policy.plan_name, null)}`}
      />
      <GoogleAuthResult />
      <GoogleConsentDialog
        purpose={consent ? "drive" : null}
        next={`/incident/${id}/documents`}
        onClose={() => setConsent(false)}
      />
      {error && (
        <p
          role="alert"
          className="m-0 rounded-btn bg-danger-soft px-4 py-2 t-caption-bold text-danger-ink"
          data-testid="error"
        >
          {error}
        </p>
      )}
      {!googleUser && (
        <p className="m-0 rounded-btn bg-paper px-4 py-2 t-caption text-muted">
          你不是用 Google 登入，文件無法存到 Google Drive，之後也不能用 Gmail 寄出送件信。
        </p>
      )}

      <section className={`${card} flex flex-col gap-1`} aria-label="還缺的文件">
        <div className="flex items-center gap-3">
          <h2 className="m-0 t-section-title text-heading">還缺的文件</h2>
          {missing.length > 0 && <Pill>{missing.length} 份</Pill>}
        </div>
        {missing.length === 0 ? (
          <p className="m-0 mt-2 t-body text-muted" data-testid="open-todos-empty">
            需上傳的文件都已備齊。
          </p>
        ) : (
          <div data-testid="open-todos">
            {groups.map((g) => (
              <div key={g.title}>
                <h3 className="m-0 mt-4.5 flex items-center gap-2 border-b border-line pt-1.5 pb-2.5 t-label text-heading before:h-4 before:w-1 before:rounded-sm before:bg-sun">
                  {g.title}
                </h3>
                <ul className="m-0 list-none p-0">
                  {g.items.map((t) => (
                    <li
                      key={t.id}
                      className="flex items-center gap-3.5 border-b border-line py-4 last:border-b-0 t-label-lg text-ink"
                    >
                      <span
                        aria-hidden="true"
                        className="size-[22px] flex-none rounded-tag border-2 border-line"
                      />
                      {t.title}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}
      </section>

      <FileDrop
        title="選擇檔案"
        description="可一次選多份，手機可直接拍照；PDF、JPG、PNG，每份 10 MB 內。上傳後依「事故類型_待辦名稱_序號」重新命名，存在你自己的 Google Drive。"
      >
        {googleUser && grant.data && !grant.data.drive ? (
          // Drive 還不能用：先說明用途再授權（授權會整頁跳走，選好的檔案會不見）
          <button
            type="button"
            className={`${btnPri} self-start`}
            disabled={closed}
            onClick={() => setConsent(true)}
            data-testid="authorize-drive"
          >
            授權 Google Drive 後上傳
          </button>
        ) : (
          <FilePickButton
            label={
              busy
                ? "上傳並辨識中…"
                : googleUser && !grant.data
                  ? "確認 Google 授權中…"
                  : "選擇檔案"
            }
            multiple
            disabled={closed || busy || !driveReady}
            onFiles={(files) => void upload(files)}
            inputTestId="doc-file"
          />
        )}
        {notices.length > 0 && (
          <div className="flex flex-col gap-2" role="status" data-testid="notice">
            {notices.map((n) => (
              <UploadNote key={n.text} status={n.status}>
                {n.text}
              </UploadNote>
            ))}
          </div>
        )}
      </FileDrop>

      {documents.length > 0 && (
        <section className={`${card} flex flex-col`} aria-label="辨識結果">
          <h2 className="m-0 mb-2 t-section-title text-heading">辨識結果</h2>
          <ul className="m-0 list-none p-0" data-testid="documents">
            {documents.map((d) => (
              <li
                key={d.id}
                className="grid grid-cols-[minmax(0,1fr)] gap-x-4 gap-y-2 border-b border-line py-3.5 last:border-b-0 md:grid-cols-[minmax(0,1fr)_auto] md:items-center"
              >
                <div className="[overflow-wrap:anywhere] t-body">
                  {d.file_name} →{" "}
                  <span className={RESULT_TONE[d.recognition_status]}>
                    {STATUS[d.recognition_status]}
                  </span>
                  {d.document_kind && `（${d.document_kind}）`}
                  {d.confirmed_by_user && " · 你已確認"}
                </div>
                {d.recognition_status === "needs_review" && !d.confirmed_by_user && (
                  <div className="flex flex-wrap items-center gap-2">
                    <select
                      aria-label={`${d.file_name} 對應的待辦`}
                      value={chosen[d.id] ?? ""}
                      onChange={(e) => setChosen((c) => ({ ...c, [d.id]: e.target.value }))}
                      className="max-w-full rounded-tag border border-line bg-white px-2.5 py-2 md:max-w-[280px]"
                    >
                      <option value="">選擇對應的待辦</option>
                      {openTodos.map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.title}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      disabled={busy || closed || !chosen[d.id]}
                      onClick={() => void confirm(d)}
                      className={btnSm}
                    >
                      確認是這份文件
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {missing.length > 0 && (
        <p className="m-0 t-caption text-muted">
          還缺的文件之後也可以回來補傳。{" "}
          <PlaceholderButton kind="link">看提醒信範本</PlaceholderButton>
        </p>
      )}

      <ActionBar twoColumns>
        <Link to="/incident/$id" params={{ id }} className={btn}>
          回理賠頁
        </Link>
        <ActionBar.Push>
          <ActionBar.Full>
            {missing.length === 0 ? (
              <Link
                to="/incident/$id/submit"
                params={{ id }}
                className={btnPri}
                data-testid="go-submit"
              >
                去送件
              </Link>
            ) : (
              <button
                type="button"
                className={btnPri}
                data-testid="upload-later"
                onClick={() => {
                  toast.show("之後可以回到理賠頁補傳文件。");
                  void navigate({ to: "/incident/$id", params: { id } });
                }}
              >
                稍後再傳
              </button>
            )}
          </ActionBar.Full>
        </ActionBar.Push>
      </ActionBar>
    </main>
  );
}
