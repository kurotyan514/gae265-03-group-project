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
  /** 這份現在有沒有存在使用者的 Google Drive（處理清單第 4 階段）；沒有這欄位視為沒有 */
  stored?: boolean;
};

export type RecognitionKind =
  | "done" // 符合規則，已自動打勾
  | "remind" // 符合規則，附提醒
  | "lack" // 符合規則，還缺另一份
  | "appended" // 追加到已完成的待辦
  | "review" // 需要你確認（已先存到 Drive）
  | "unsaved" // 沒有完成：沒有存到 Drive（不確定、又沒有授權或存檔失敗）
  | "incomplete" // 不合格
  | "unreadable" // 無法辨識
  | "not_matched" // 辨識失敗
  | "error"; // 上傳本身失敗（網路、伺服器）

/** 四個處理階段（GLOSSARY「處理階段」）；沒有「讀取內容」。 */
export const STAGE_NAMES = [
  "認出文件種類",
  "對應待辦",
  "檢查內容",
  "存到你的 Google Drive",
] as const;

export type StageState = "ok" | "stop" | "nosave" | "saved" | "unknown" | "skip";

const STAGE_LABEL: Record<StageState, string> = {
  ok: "通過",
  stop: "停在這裡",
  nosave: "沒有存",
  saved: "已先存（待你確認）",
  unknown: "未確認",
  skip: "未進行",
};

export type StageResult = { name: string; state: StageState; label: string };
export type Tone = "ok" | "warn" | "bad" | "wait";

/** 一份文件處理完的結果：標籤、各階段、一行說明；全部由辨識結果推得，不含文件上的內容。 */
export type RecognitionOutcome = {
  kind: RecognitionKind;
  /** 合格：折疊進「看全部明細」；其餘都要列出來 */
  passed: boolean;
  badge: { text: string; tone: Tone };
  stages: StageResult[];
  /** 沒通過：停在哪、有沒有存到 Google Drive、下一步（紅字或琥珀）；合格：選配的備註 */
  note?: string;
};

export type ProcessingRow = {
  key: string;
  name: string;
  /** wait 等待中、run 小助理處理中、done 有結果（或上傳失敗） */
  phase: "wait" | "run" | "done";
  kind?: RecognitionKind;
  outcome?: RecognitionOutcome;
  /** 上傳或重新檢查本身失敗的訊息 */
  error?: string;
  /** 需要你確認：文件編號、6 號認為可能的待辦、使用者選到哪一項 */
  docId?: string;
  candidates?: string[];
  choice?: string;
  expanded?: boolean;
  busy?: boolean;
};

/** 處理中的批次文字（元件旁不放常數，統一在這裡） */
export const WORKING_TEXT = "小助理正在處理這份文件…";
export const SLOW_TEXT = "照片需要久一點，請稍候";
export const WAITING_TEXT = "等待中";
/** 單份處理超過這麼久（毫秒）才追加安撫 */
export const SLOW_AFTER_MS = 8000;

const NOT_SAVED = "這份沒有存到你的 Google Drive";
const SAVED_PENDING = "已先存到你的 Google Drive，等你確認後才算正式";

/** 「已收到，還缺登機證（或改傳一份搭機證明）；…」→「還缺登機證」 */
export function lackText(reason: string | null | undefined): string {
  const first = (reason ?? "").split("；")[0] ?? "";
  return first.replace(/^已收到，/, "").replace(/（.*$/, "") || "還缺其他文件";
}

/** 去掉句尾標點，接在別的句子後面不會變成「。。」 */
const clip = (text: string | null | undefined) => (text ?? "").trim().replace(/[。.\s]+$/, "");

function stages(states: [StageState, StageState, StageState, StageState]): StageResult[] {
  return states.map((state, i) => ({
    name: STAGE_NAMES[i] ?? "",
    state,
    label: STAGE_LABEL[state],
  }));
}

/**
 * 辨識結果 → 這份文件的標籤與四個階段各自的狀態（規則同設計稿的「情況對照表」，依契約 document_agent.py）。
 * 第 4 階段看 `stored`：只有真的存到 Drive 才是通過；不確定且已先存是「已先存（待你確認）」。
 */
export function describeRecognition(doc: UploadedDocument): RecognitionOutcome {
  const stored = doc.stored === true;
  const reason = clip(doc.reason);
  switch (doc.recognition_status) {
    case "recognized": {
      if (!stored)
        return {
          kind: "unsaved",
          passed: false,
          badge: { text: "沒有完成：沒有存到你的 Google Drive", tone: "bad" },
          stages: stages(["ok", "ok", "ok", "nosave"]),
          note: `${NOT_SAVED}。待辦還沒有勾`,
        };
      const kind: RecognitionKind = doc.appended
        ? "appended"
        : !doc.todo_complete
          ? "lack"
          : reason
            ? "remind"
            : "done";
      const text =
        kind === "lack"
          ? `已處理：通過，${lackText(doc.reason)}`
          : kind === "appended"
            ? "已處理：通過，已追加到已完成的待辦"
            : kind === "remind"
              ? "已處理：通過（有提醒）"
              : "已處理：通過";
      return {
        kind,
        passed: true,
        badge: { text, tone: "ok" },
        stages: stages(["ok", "ok", "ok", "ok"]),
        note: kind === "remind" ? `提醒：${reason}` : undefined,
      };
    }
    case "incomplete": {
      const lacking = doc.missing?.length ? `缺少${doc.missing.join("、")}` : reason;
      const next = doc.next_step ? `。下一步：${clip(doc.next_step)}` : "";
      return {
        kind: "incomplete",
        passed: false,
        badge: { text: "已處理：不合格", tone: "bad" },
        stages: stages(["ok", "ok", "stop", "nosave"]),
        note: `停在「檢查內容」：${lacking}。${NOT_SAVED}${next}`,
      };
    }
    case "needs_review":
      if (stored)
        return {
          kind: "review",
          passed: false,
          badge: { text: "需要你確認", tone: "warn" },
          stages: stages(["ok", "stop", "skip", "saved"]),
          note: `小助理不確定這份對應哪一項待辦，請在下面選一項。${SAVED_PENDING}`,
        };
      return {
        kind: "unsaved",
        passed: false,
        badge: { text: "沒有完成：沒有存到你的 Google Drive", tone: "bad" },
        stages: stages(["unknown", "unknown", "unknown", "nosave"]),
        note: `${NOT_SAVED}${reason ? `：${reason}` : ""}。待辦還沒有勾。下一步：稍後再傳一次，或先授權 Google Drive`,
      };
    case "failed":
      if (doc.failure === "not_matched")
        return {
          kind: "not_matched",
          passed: false,
          badge: { text: "已處理：不在待辦清單", tone: "bad" },
          stages: stages(["ok", "stop", "skip", "nosave"]),
          note: `停在「對應待辦」：${reason || "這份文件不在這次事故的待辦清單中"}。${NOT_SAVED}`,
        };
      return {
        kind: "unreadable",
        passed: false,
        badge: { text: "已處理：讀不出來", tone: "bad" },
        stages: stages(["stop", "skip", "skip", "nosave"]),
        note: `停在「認出文件種類」：${reason || "小助理看不清楚這份文件，請拍清楚一點再上傳"}。${NOT_SAVED}`,
      };
    default:
      return {
        kind: "error",
        passed: false,
        badge: { text: "上傳失敗", tone: "bad" },
        stages: stages(["unknown", "unknown", "unknown", "nosave"]),
      };
  }
}

/** 這一列的標籤：還沒有結果時是「等待中」或「處理中」；上傳失敗沒有四階段結果 */
export function rowBadge(row: ProcessingRow): { text: string; tone: Tone } {
  if (row.outcome) return row.outcome.badge;
  if (row.kind === "error") return { text: "上傳失敗", tone: "bad" };
  return { text: row.phase === "run" ? "處理中" : WAITING_TEXT, tone: "wait" };
}

/** 摘要預設只列沒通過的；合格的收在「看全部明細」 */
export const isPassed = (row: ProcessingRow) => row.outcome?.passed === true;
