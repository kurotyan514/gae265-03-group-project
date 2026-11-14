import { useEffect, useState } from "react";
import { discardPendingTripDocuments, recheckTripDocument, rejectTripDocument } from "../../client";
import type { TodoView, TripOut } from "../../client/types.gen";
import { btnPri } from "../../components/ui/buttons";
import { GoogleConsentDialog } from "../google/GoogleConsentDialog";
import { useGoogleGrant } from "../google/useGoogleGrant";
import { dateOf } from "../incident/IncidentCard";
import { UploadBox, type UploadSource } from "../incident/UploadBox";
import { useTrip } from "./useTrip";

/** 不符保障事故裡有範本的待辦（和待辦清單的反灰一致）：不收文件，不算「還缺」。 */
const greyed = (todo: TodoView, covered: boolean) => !covered && todo.template_id != null;

const nameOf = (i: TripOut["incidents"][number]) =>
  `${i.incident_type_name ?? "事故"}${dateOf(i) ? ` · ${dateOf(i)}` : ""}`;

/**
 * 行程頁的上傳框（ADR-0029）：整個行程一個，6 號跨事故對應；同一份文件對到多個事故的待辦時
 * 回「需要你確認」並列出候選（選單與說明都帶事故名稱）。文件存到使用者的 Google Drive，
 * 所以 Google 登入的使用者要先授權 Drive。
 */
export function TripUploader({
  policyId,
  trip,
  googleUser,
  onError,
}: {
  policyId: string;
  trip: TripOut;
  googleUser: boolean;
  onError: (message: string | null) => void;
}) {
  const { setTrip } = useTrip(policyId);
  const grant = useGoogleGrant(googleUser);
  const [consent, setConsent] = useState(false);
  const [openedAt] = useState(() => new Date().toISOString());

  const documents = [...trip.shared_documents, ...trip.incidents.flatMap((i) => i.documents)];
  const leftOver = documents.some(
    (d) => d.recognition_status === "needs_review" && !d.confirmed_by_user,
  );
  // 上次「需要你確認」沒選就離開：檔案不保存，打開行程時清掉（雲端的檔案一起刪）
  // biome-ignore lint/correctness/useExhaustiveDependencies: 只在打開頁面時清一次
  useEffect(() => {
    if (trip.locked || !leftOver) return;
    void discardPendingTripDocuments({
      path: { policy_id: policyId },
      body: { before: openedAt },
    }).then((res) => {
      if (res.data) setTrip(res.data);
    });
  }, []);

  // 同類型同一天的事故名稱會一樣：第二次起加「（2）」，選單才分得出來（和 7 號的信一致）
  const seen = new Map<string, number>();
  const owners = new Map<string, string>();
  for (const i of trip.incidents) {
    const base = nameOf(i);
    const n = (seen.get(base) ?? 0) + 1;
    seen.set(base, n);
    for (const t of i.todos) owners.set(t.id, n > 1 ? `${base}（${n}）` : base);
  }
  const todos = [...trip.shared_todos, ...trip.incidents.flatMap((i) => i.todos)];
  const label = (t: TodoView) =>
    t.scope === "policy" ? `整個行程｜${t.title}` : `${owners.get(t.id) ?? "事故"}｜${t.title}`;
  const source: UploadSource = {
    uploadUrl: `/api/v1/policies/${policyId}/documents`,
    readUrl: `/api/v1/policies/${policyId}/trip`,
    todos,
    documents,
    snapshot: (json) => {
      const t = json as TripOut;
      return {
        todos: [...t.shared_todos, ...t.incidents.flatMap((i) => i.todos)],
        documents: [...t.shared_documents, ...t.incidents.flatMap((i) => i.documents)],
      };
    },
    groupOf: (t) => (t.scope === "policy" ? "整個行程" : (owners.get(t.id) ?? "事故")),
    optionLabel: label,
    recheck: (documentId, todoId) =>
      recheckTripDocument({
        path: { policy_id: policyId, document_id: documentId },
        body: { todo_id: todoId },
      }),
    reject: (documentId) =>
      rejectTripDocument({ path: { policy_id: policyId, document_id: documentId } }),
  };

  const driveReady = !googleUser || grant.data?.drive === true;
  const missing =
    trip.shared_todos.filter((t) => t.requires_upload && !t.is_done && t.applicable !== false)
      .length +
    trip.incidents.reduce(
      (n, i) =>
        n +
        i.todos.filter(
          (t) => t.requires_upload && !t.is_done && t.applicable !== false && !greyed(t, i.covered),
        ).length,
      0,
    );
  const hasUncovered = trip.incidents.some((i) => !i.covered);

  return (
    // 待辦清單的「上傳」按鈕用 #upload-box 捲到這裡
    <div id="upload-box" className="scroll-mt-24 flex flex-col gap-2">
      <GoogleConsentDialog
        purpose={consent ? "drive" : null}
        next={`/trip/${policyId}`}
        onClose={() => setConsent(false)}
      />
      <UploadBox
        source={source}
        missingCount={missing}
        disabled={trip.locked || !driveReady}
        action={
          googleUser && grant.data && !grant.data.drive ? (
            <button
              type="button"
              className={`${btnPri} self-start`}
              onClick={() => setConsent(true)}
              data-testid="authorize-drive"
            >
              授權 Google Drive 後上傳
            </button>
          ) : googleUser && !grant.data ? (
            <span className="t-caption text-muted">確認 Google 授權中…</span>
          ) : undefined
        }
        onStart={() => onError(null)}
        onUploaded={(fresh) => {
          if (fresh) setTrip(fresh as TripOut);
        }}
      />
      {hasUncovered && (
        <p className="m-0 t-caption text-muted" data-testid="upload-uncovered-note">
          有事故依條款不在保障範圍，它的文件不需要上傳，上傳的檔案也不會對應到那些事故。
        </p>
      )}
    </div>
  );
}
