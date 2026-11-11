import type { DocumentView } from "../../client/types.gen";

/** 上傳回應（POST /incidents/{id}/documents）裡處理列用到的欄位。 */
export type UploadedDocument = {
  id?: string;
  file_name: string;
  recognition_status: DocumentView["recognition_status"];
  document_kind?: string | null;
  todo_id?: string | null;
  reason?: string | null;
  failure?: "unreadable" | "not_matched" | null;
  found_fields?: string[];
  todo_complete?: boolean;
  appended?: boolean;
  missing?: string[];
  next_step?: string | null;
  candidate_todo_ids?: string[];
};

export type ProcessingStep = "wait" | "run" | "ok" | "bad";
export type RecognitionKind =
  | "done" // 符合規則，已自動打勾
  | "remind" // 符合規則，附提醒
  | "lack" // 符合規則，還缺另一份
  | "appended" // 追加到已完成的待辦
  | "review" // 需要你確認
  | "incomplete" // 不合格
  | "unreadable" // 無法辨識
  | "not_matched" // 辨識失敗
  | "error"; // 上傳本身失敗（網路、伺服器）

export type ProcessingRow = {
  key: string;
  name: string;
  steps: [ProcessingStep, ProcessingStep, ProcessingStep];
  kind?: RecognitionKind;
  /** 判斷依據（結果下面那一行） */
  why?: string;
  /** 還缺什麼（kind 為 lack 時，例：還缺登機證） */
  lack?: string;
  /** 不合格時缺少的欄位（例：延誤期間） */
  missing?: string[];
  /** 需要你確認：文件編號、6 號認為可能的待辦、使用者選到哪一項 */
  docId?: string;
  candidates?: string[];
  choice?: string;
  expanded?: boolean;
  busy?: boolean;
};

export const STEP_NAMES = ["讀取內容", "對應待辦", "檢查規則"] as const;

/** 將 6 號的辨識結果歸成既有畫面種類與停止步驟。 */
export function classifyRecognition(doc: UploadedDocument): {
  kind: RecognitionKind;
  failAt: number;
} {
  const reason = doc.reason ?? "";
  switch (doc.recognition_status) {
    case "recognized":
      if (doc.appended) return { kind: "appended", failAt: 3 };
      if (!doc.todo_complete) return { kind: "lack", failAt: 3 };
      return { kind: reason ? "remind" : "done", failAt: 3 };
    case "incomplete":
      return { kind: "incomplete", failAt: 2 };
    case "needs_review":
      return { kind: "review", failAt: 1 };
    case "failed":
      return doc.failure === "not_matched"
        ? { kind: "not_matched", failAt: 1 }
        : { kind: "unreadable", failAt: 0 };
    default:
      return { kind: "error", failAt: 0 };
  }
}

/** 「已收到，還缺登機證（或改傳一份搭機證明）；…」→「還缺登機證」 */
export function lackText(reason: string | null | undefined): string {
  const first = (reason ?? "").split("；")[0] ?? "";
  return first.replace(/^已收到，/, "").replace(/（.*$/, "") || "還缺其他文件";
}

export function recognitionBadge(row: ProcessingRow): {
  text: string;
  tone: "ok" | "warn" | "bad" | "wait";
} {
  if (!row.kind) {
    const index = row.steps.indexOf("run");
    return { text: index >= 0 ? `${STEP_NAMES[index]}中…` : "等待中", tone: "wait" };
  }
  const text: Record<RecognitionKind, string> = {
    done: "符合規則，已自動打勾",
    remind: "符合規則，已自動打勾（有提醒）",
    lack: "",
    appended: "已追加到已完成的待辦",
    review: "需要你確認",
    incomplete: "不合格（檔案未保留）",
    unreadable: "無法辨識（檔案未保留）",
    not_matched: "辨識失敗：不在待辦清單中（檔案未保留）",
    error: "上傳失敗",
  };
  const accepted = ["done", "remind", "lack", "appended"].includes(row.kind);
  return {
    text:
      row.kind === "lack"
        ? `符合規則，${row.lack ?? "還缺其他文件"}`
        : row.kind === "incomplete" && row.missing?.length
          ? `不合格：缺少${row.missing.join("、")}（檔案未保留）`
          : text[row.kind],
    tone: accepted ? "ok" : row.kind === "review" ? "warn" : "bad",
  };
}
