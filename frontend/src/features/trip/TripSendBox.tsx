import { useEffect, useState } from "react";
import { closeTrip, getTripDriveFolder } from "../../client";
import type { TripOut } from "../../client/types.gen";
import { btn, btnPri, btnSm } from "../../components/ui/buttons";
import { Dialog, DialogShell } from "../../components/ui/DialogShell";
import { PlaceholderButton } from "../../components/ui/PlaceholderButton";
import { Pill } from "../../components/ui/Tag";
import { closedText } from "../incident/closedLinks";
import { card, errorText } from "../incident/shared";
import { tripPending } from "./TripTodoCards";
import { useTrip } from "./useTrip";

/** 結案後的「下載全部文件」：行程的 Google Drive 資料夾；只放行 Drive 的網址（後端也擋過一次）。 */
function useDriveUrl(policyId: string, locked: boolean): string | null {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!locked) return setUrl(null);
    let alive = true;
    void getTripDriveFolder({ path: { policy_id: policyId } }).then((res) => {
      const folder = res.data?.url;
      if (alive) setUrl(folder?.startsWith("https://drive.google.com/") ? folder : null);
    });
    return () => {
      alive = false;
    };
  }, [policyId, locked]);
  return url;
}

/**
 * 行程頁的送件區（ADR-0029、規格 7.3.4）：整個行程一起送件。
 * 還缺文件 → 「還缺 N 份文件」＋上傳文件；待辦沒勾完 → 說明；備齊 → 「文件已備齊」＋送件；
 * 所有事故都不符保障 → 「結案」（不寄信、不寫送件紀錄）；
 * 結案後依當時的選擇說明，「到 Gmail 查看」「下載全部文件」拿得到連結才亮，否則反灰。
 */
export function TripSendBox({ policyId, trip }: { policyId: string; trip: TripOut }) {
  const { refresh } = useTrip(policyId);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { missingUploads, pending } = tripPending(trip);
  const hasFiles = [...trip.shared_documents, ...trip.incidents.flatMap((i) => i.documents)].some(
    (d) => d.storage_path,
  );
  const driveUrl = useDriveUrl(policyId, trip.locked);
  const gmail = trip.submission.gmail_url;
  const gmailUrl = gmail?.startsWith("https://mail.google.com/") ? gmail : null;

  async function close() {
    setBusy(true);
    setError(null);
    const res = await closeTrip({ path: { policy_id: policyId } });
    setBusy(false);
    setConfirming(false);
    if (!res.data) return setError(errorText(res.error, res.response?.status));
    await refresh();
  }

  return (
    <section
      className={`${card} flex flex-wrap items-center gap-x-5 gap-y-3`}
      aria-label="送件"
      data-testid="send-box"
    >
      <h2 className="m-0 text-xl font-bold text-heading">送件</h2>
      {trip.locked ? (
        <>
          <p className="m-0 t-body text-muted" data-testid="send-closed">
            {trip.submission.status
              ? closedText(trip.submission.status, hasFiles)
              : "這個行程的事故都不在保障範圍，已結案，沒有寄出信件。"}
          </p>
          <div className="ml-auto flex flex-wrap gap-3">
            {gmailUrl ? (
              <a
                href={gmailUrl}
                target="_blank"
                rel="noopener noreferrer"
                className={btnSm}
                data-testid="send-box-gmail"
              >
                到 Gmail 查看
              </a>
            ) : (
              <PlaceholderButton kind="small">到 Gmail 查看</PlaceholderButton>
            )}
            {hasFiles && driveUrl ? (
              <a
                href={driveUrl}
                target="_blank"
                rel="noopener noreferrer"
                className={btnSm}
                data-testid="send-box-drive"
              >
                下載全部文件
              </a>
            ) : (
              <PlaceholderButton kind="small">下載全部文件</PlaceholderButton>
            )}
          </div>
        </>
      ) : trip.can_close ? (
        <>
          <Pill tone="need">事故都不在保障範圍</Pill>
          <p className="m-0 t-caption text-muted">不需要寄信，可以直接結案。</p>
          <div className="ml-auto">
            <button
              type="button"
              className={btnPri}
              onClick={() => setConfirming(true)}
              data-testid="close-trip"
            >
              結案
            </button>
          </div>
        </>
      ) : missingUploads > 0 ? (
        <>
          <Pill tone="need">還缺 {missingUploads} 份文件</Pill>
          <div className="ml-auto">
            {/* 上傳框就在這一頁待辦區上方，捲過去 */}
            <a href="#upload-box" className={btnSm}>
              上傳文件
            </a>
          </div>
        </>
      ) : pending > 0 ? (
        <>
          <Pill tone="need">還有 {pending} 項待辦沒完成</Pill>
          <p className="m-0 t-caption text-muted">勾完待辦後就能送件。</p>
        </>
      ) : (
        <>
          <Pill tone="sent">文件已備齊</Pill>
          <div className="ml-auto">
            {/* 行程版送件頁（F4b）接上後換成連結 */}
            <PlaceholderButton kind="small" data-testid="go-submit">
              送件
            </PlaceholderButton>
          </div>
        </>
      )}
      {error && (
        <p
          role="alert"
          className="m-0 basis-full t-caption-bold text-danger-ink"
          data-testid="send-error"
        >
          {error}
        </p>
      )}
      <DialogShell
        open={confirming}
        onOpenChange={(open) => !open && setConfirming(false)}
        title="結案這個行程？"
        description={
          <p>所有事故都不在保障範圍，結案後不會寄出任何信件，之後也不能再新增事故或修改。</p>
        }
        testId="close-dialog"
        actions={
          <>
            <Dialog.Close className={btn}>取消</Dialog.Close>
            <button
              type="button"
              className={btnPri}
              disabled={busy}
              onClick={() => void close()}
              data-testid="close-confirm"
            >
              {busy ? "結案中…" : "確定結案"}
            </button>
          </>
        }
      />
    </section>
  );
}
