import { Button } from "@base-ui/react/button";
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { googleRevokeMutation } from "../../client/@tanstack/react-query.gen";
import type { GoogleGrantOut } from "../../client/types.gen";
import { GoogleAuthResult } from "./GoogleAuthResult";
import { GoogleConsentDialog } from "./GoogleConsentDialog";
import type { GooglePurpose } from "./google";
import { useGoogleGrant } from "./useGoogleGrant";

const buttonClass =
  "rounded-md border px-3 py-1 hover:bg-gray-100 data-[disabled]:opacity-50 disabled:opacity-50";

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
    <section className="space-y-2 rounded-md border p-3" data-testid="google-grant">
      <h2 className="text-lg font-bold">Google 授權</h2>
      <GoogleAuthResult />
      {grant.isPending && <p className="text-gray-600">正在向 Google 確認授權狀態…</p>}
      {grant.isError && (
        <p role="alert" className="text-red-600">
          無法取得授權狀態，請重新整理再試一次。
        </p>
      )}
      {grant.data && (
        <>
          <ul className="space-y-1">
            {ITEMS.map(({ purpose, label }) => {
              const usable = grant.data[purpose];
              return (
                <li key={purpose} className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{label}</span>
                  <span
                    className={usable ? "text-green-800" : "text-gray-600"}
                    data-testid={`grant-${purpose}`}
                  >
                    {stateText(grant.data, usable)}
                  </span>
                  {!usable && (
                    <Button
                      className={buttonClass}
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
            <div className="space-y-2">
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
                  className="space-y-2 rounded-md bg-gray-50 p-2"
                  data-testid="google-revoke-confirm"
                >
                  <p>
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
                <p role="alert" className="text-red-600">
                  取消授權失敗，請再試一次。
                </p>
              )}
            </div>
          )}
        </>
      )}
      <GoogleConsentDialog purpose={consent} next={next} onClose={() => setConsent(null)} />
    </section>
  );
}
