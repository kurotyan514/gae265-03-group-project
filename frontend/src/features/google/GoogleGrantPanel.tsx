import { Button } from "@base-ui/react/button";
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { googleRevokeMutation } from "../../client/@tanstack/react-query.gen";
import type { GoogleGrantOut } from "../../client/types.gen";
import { ShieldIcon } from "../../components/icons";
import { btnSm, btnSmPri } from "../../components/ui/buttons";
import { GoogleAuthResult } from "./GoogleAuthResult";
import { GoogleConsentDialog } from "./GoogleConsentDialog";
import type { GooglePurpose } from "./google";
import { useGoogleGrant } from "./useGoogleGrant";

const buttonClass = btnSm;

const ITEMS: { purpose: GooglePurpose; label: string }[] = [
  { purpose: "drive", label: "Google Drive（存放理賠文件）" },
  { purpose: "gmail", label: "Gmail（寄出送件信）" },
];

function stateText(grant: GoogleGrantOut, usable: boolean): string {
  if (usable) return "可以使用";
  if (grant.status === "invalid") return "已失效，需要重新授權";
  if (grant.status === "revoked") return "已取消";
  return "尚未授權";
}

/** 帳號頁的 Google 授權：看 Drive、Gmail 能不能用，授權或取消授權（ADR-0020）。 */
export function GoogleGrantPanel({ next }: { next: string }) {
  const grant = useGoogleGrant();
  const [consent, setConsent] = useState<GooglePurpose | null>(null);
  const [confirming, setConfirming] = useState(false);
  const revoke = useMutation({
    ...googleRevokeMutation(),
    onSuccess: async () => {
      setConfirming(false);
      await grant.refetch();
    },
  });

  return (
    <section
      aria-labelledby="google-grant-title"
      className="rounded-2xl border border-line/60 bg-white px-3 pt-4 pb-4 shadow-card md:rounded-3xl md:px-4 md:pt-5 md:pb-5"
      data-testid="google-grant"
    >
      <div className="flex items-center gap-2.5 border-b border-line pt-1 pb-3.5 pl-1 md:gap-3.5 md:pt-0 md:pb-[18px] md:pl-2">
        <ShieldIcon className="size-7 flex-none text-leaf md:size-9" />
        <h2
          id="google-grant-title"
          className="text-xl font-bold leading-[30px] text-heading md:text-2xl md:leading-9"
        >
          Google 授權
        </h2>
      </div>
      <div className="space-y-4 px-1 pt-4 md:px-2">
        <GoogleAuthResult />
        {grant.isPending && <p className="m-0 t-body text-muted">正在向 Google 確認授權狀態…</p>}
        {grant.isError && (
          <p role="alert" className="m-0 t-caption-bold text-danger">
            無法取得授權狀態，請重新整理再試一次。
          </p>
        )}
        {grant.data && (
          <>
            <ul className="m-0 list-none space-y-3 p-0">
              {ITEMS.map(({ purpose, label }) => {
                const usable = grant.data[purpose];
                return (
                  <li key={purpose} className="flex flex-wrap items-center gap-x-3 gap-y-2">
                    <span className="t-label min-w-[220px] text-ink">{label}</span>
                    <span className="inline-flex items-center gap-1.5 t-caption-bold text-ink">
                      <span
                        aria-hidden="true"
                        className={`size-2 flex-none rounded-full ${usable ? "bg-leaf" : "bg-coral"}`}
                      />
                      <span data-testid={`grant-${purpose}`}>{stateText(grant.data, usable)}</span>
                    </span>
                    {!usable && (
                      <Button
                        className={btnSmPri}
                        onClick={() => setConsent(purpose)}
                        data-testid={`grant-${purpose}-authorize`}
                      >
                        授權
                      </Button>
                    )}
                  </li>
                );
              })}
            </ul>
            {(grant.data.status === "active" || grant.data.status === "invalid") && (
              <div className="space-y-3">
                {!confirming ? (
                  <Button
                    className={buttonClass}
                    onClick={() => setConfirming(true)}
                    data-testid="google-revoke"
                  >
                    取消 Google 授權
                  </Button>
                ) : (
                  <div
                    className="space-y-3 rounded-tile border border-line bg-paper p-4"
                    data-testid="google-revoke-confirm"
                  >
                    <p className="m-0 t-body text-ink">
                      確定要取消嗎？取消後就不能再替你存放文件或寄出送件信，需要時可以再授權。
                      已存進你 Google Drive 的文件與 Gmail 裡的草稿不會被刪除。
                    </p>
                    <div className="flex gap-2">
                      <Button
                        className={buttonClass}
                        onClick={() => revoke.mutate({})}
                        disabled={revoke.isPending}
                        data-testid="google-revoke-yes"
                      >
                        確定取消
                      </Button>
                      <Button className={buttonClass} onClick={() => setConfirming(false)}>
                        保留
                      </Button>
                    </div>
                  </div>
                )}
                {revoke.isError && (
                  <p role="alert" className="m-0 t-caption-bold text-danger">
                    取消授權失敗，請再試一次。
                  </p>
                )}
              </div>
            )}
          </>
        )}
      </div>
      <GoogleConsentDialog purpose={consent} next={next} onClose={() => setConsent(null)} />
    </section>
  );
}
