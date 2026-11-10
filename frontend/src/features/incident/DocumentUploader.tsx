import { useState } from "react";
import type { IncidentContext } from "../../client/types.gen";
import { btnPri } from "../../components/ui/buttons";
import { GoogleConsentDialog } from "../google/GoogleConsentDialog";
import { useGoogleGrant } from "../google/useGoogleGrant";
import { useIncident } from "./shared";
import { UploadBox } from "./UploadBox";

/**
 * 上傳理賠文件的唯一入口（2-3 理賠頁與 2-4 共用）：外觀與流程照 Leon 原型 2-3i（見 `UploadBox`）。
 * 文件存到使用者的 Google Drive，所以 Google 登入的使用者要先授權 Drive，這一層負責授權。
 */
export function DocumentUploader({
  id,
  ctx,
  googleUser,
  /** 授權 Google 後要回到的頁面。 */
  next,
  onError,
}: {
  id: string;
  ctx: IncidentContext;
  googleUser: boolean;
  next: string;
  onError: (message: string | null) => void;
}) {
  const { setIncident } = useIncident(id);
  const grant = useGoogleGrant(googleUser);
  const [consent, setConsent] = useState(false);

  const closed = ctx.status === "completed";
  const driveReady = !googleUser || grant.data?.drive === true;
  const missing = (ctx.todos ?? []).filter(
    (t) => t.requires_upload && !t.is_done && t.applicable !== false,
  ).length;

  return (
    // 待辦清單的「上傳」按鈕用 #upload-box 捲到這裡
    <div id="upload-box" className="scroll-mt-24">
      <GoogleConsentDialog
        purpose={consent ? "drive" : null}
        next={next}
        onClose={() => setConsent(false)}
      />
      <UploadBox
        id={id}
        ctx={ctx}
        missingCount={missing}
        disabled={closed || !driveReady}
        action={
          googleUser && grant.data && !grant.data.drive ? (
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
          ) : googleUser && !grant.data ? (
            <span className="t-caption text-muted">確認 Google 授權中…</span>
          ) : undefined
        }
        onStart={() => onError(null)}
        onUploaded={(fresh) => {
          if (fresh) setIncident(fresh);
        }}
      />
    </div>
  );
}
