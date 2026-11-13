import { useEffect, useState } from "react";
import { getIncidentDriveFolder, getIncidentSubmission } from "../../client";

export type ClosedAs = "sent" | "drafted" | "self_submitted";

/** 理賠頁送件區：依結案時的選擇、有沒有上傳文件，說明信與文件在哪裡。 */
const CLOSED_TEXT: Record<ClosedAs, { withFiles: string; noFiles: string }> = {
  sent: {
    withFiles: "已替你送件並於你的 Gmail 寄件備份留存紀錄，文件也已存在你的 Google Drive。",
    noFiles: "已替你送件並於你的 Gmail 寄件備份留存紀錄，但此次理賠未上傳任何文件至 Google Drive。",
  },
  drafted: {
    withFiles: "已在你的 Gmail 建立草稿，文件也已存在你的 Google Drive。",
    noFiles: "已在你的 Gmail 建立草稿，但此次理賠未上傳任何文件至 Google Drive。",
  },
  self_submitted: {
    withFiles: "未在你的 Gmail 建立草稿，但文件已存在你的 Google Drive。",
    noFiles: "未在你的 Gmail 建立草稿，此次理賠也未上傳任何文件至 Google Drive。",
  },
};
/** 加上送件紀錄之前結案的事件不知道選了什麼。 */
const CLOSED_FALLBACK = {
  withFiles: "已送件結案，文件已存在你的 Google Drive。",
  noFiles: "已送件結案，此次理賠未上傳任何文件至 Google Drive。",
};

export function closedText(closedAs: ClosedAs | null, hasFiles: boolean): string {
  const texts = closedAs ? CLOSED_TEXT[closedAs] : CLOSED_FALLBACK;
  return hasFiles ? texts.withFiles : texts.noFiles;
}

export type ClosedLinks = {
  closedAs: ClosedAs | null;
  /** Gmail 網頁上那封寄出的信或那份草稿；自己處理或沒有信件編號時是 null。 */
  gmailUrl: string | null;
  /** Google Drive 上這次的行程資料夾；沒有 Drive 授權時是 null。 */
  driveUrl: string | null;
};

const EMPTY: ClosedLinks = { closedAs: null, gmailUrl: null, driveUrl: null };

/**
 * 結案後的「到 Gmail 查看」「下載全部文件」連結。只放行 Gmail 與 Google Drive 的網址（後端也擋過一次）。
 * 送件頁寄出後事件變成結案，就會讀一次。
 */
export function useClosedLinks(id: string, closed: boolean): ClosedLinks {
  const [links, setLinks] = useState<ClosedLinks>(EMPTY);
  useEffect(() => {
    if (!closed) return setLinks(EMPTY);
    let alive = true;
    void Promise.all([
      getIncidentSubmission({ path: { incident_id: id } }),
      getIncidentDriveFolder({ path: { incident_id: id } }),
    ]).then(([submission, drive]) => {
      if (!alive) return;
      const gmail = submission.data?.gmail_url;
      const folder = drive.data?.url;
      setLinks({
        closedAs: submission.data?.status ?? null,
        gmailUrl: gmail?.startsWith("https://mail.google.com/") ? gmail : null,
        driveUrl: folder?.startsWith("https://drive.google.com/") ? folder : null,
      });
    });
    return () => {
      alive = false;
    };
  }, [id, closed]);
  return links;
}
