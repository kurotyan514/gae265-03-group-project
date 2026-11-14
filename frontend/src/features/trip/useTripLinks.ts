import { useEffect, useState } from "react";
import { getTripDriveFolder } from "../../client";
import type { TripOut } from "../../client/types.gen";
import type { ClosedLinks } from "../incident/closedLinks";

/** 結案後的「下載全部文件」：行程的 Google Drive 資料夾；只放行 Drive 的網址（後端也擋過一次）。 */
export function useDriveUrl(policyId: string, locked: boolean): string | null {
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

/** 行程結案後的連結（結案方式、Gmail、Drive）：只放行 Gmail 與 Google Drive 的網址。 */
export function useTripLinks(policyId: string, trip: TripOut | undefined): ClosedLinks {
  const driveUrl = useDriveUrl(policyId, trip?.locked ?? false);
  const gmail = trip?.submission.gmail_url;
  return {
    closedAs: trip?.submission.status ?? null,
    gmailUrl: gmail?.startsWith("https://mail.google.com/") ? gmail : null,
    driveUrl,
  };
}
