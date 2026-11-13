import type { DocumentView, IncidentContext } from "../../client/types.gen";

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
  | "remind" // 符合規則，已自動打勾，附提醒
  | "lack" // 符合規則，還缺另一份
  | "appended" // 追加到已完成的待辦
  | "review" // 需要你確認（已先存到 Drive）
  | "unsaved" // 沒有完成：沒有存到 Drive（不確定、又沒有授權或存檔失敗）
  | "incomplete" // 不合格
  | "unreadable" // 無法辨識
  | "not_matched" // 辨識失敗
  | "error"; // 上傳本身失敗（網路、伺服器）

export type Tone = "ok" | "warn" | "bad" | "wait";

/** 一份文件處理完的結果：標籤與一行說明；全部由辨識結果推得，不含文件上的內容。 */
export type RecognitionOutcome = {
  kind: RecognitionKind;
  /** 合格（通過、追加、還缺另一份）且沒有提醒：預設折疊進「看全部明細」；其餘都要列出來 */
  collapsed: boolean;
  /** 有提醒（任何一種合格結果都可能帶）：不折疊、琥珀色，摘要算進「有提醒」 */
  hasReminder: boolean;
  badge: { text: string; tone: Tone };
  /** 沒通過：原因與下一步（紅字或琥珀；不寫停在哪個階段、有沒有存到 Drive，標籤已說明）；合格：選配的備註 */
  note?: string;
};

export type ProcessingRow = {
  key: string;
  name: string;
  /** wait 等待中、run 小助理處理中、done 有結果（或上傳失敗） */
  phase: "wait" | "run" | "done";
  /** 處理中亮到第幾步（0 起算）；已亮過的步驟打勾，這一步轉圈 */
  stage?: number;
  kind?: RecognitionKind;
  outcome?: RecognitionOutcome;
  /** 判斷依據（對應：事故｜待辦｜辨識到：欄位名稱），有對應到待辦才有 */
  basis?: string;
  /** 上傳或重新檢查本身失敗的訊息 */
  error?: string;
  /** 需要你確認：文件編號、6 號認為可能的待辦、使用者選到哪一項 */
  docId?: string;
  candidates?: string[];
  choice?: string;
  expanded?: boolean;
  busy?: boolean;
};

/**
 * 處理中的三個階段（設計者 11/13，改回 ADR-0027 之前的樣子）：逐步亮起，最短 MIN_PLAY_MS 演完，
 * 每份只演一次；伺服器還沒回來時停在最後一步轉圈，結果出來就換成標籤。階段是示意，不代表小助理真的做到哪，
 * 所以不包含「存到 Google Drive」（有沒有存由結果標籤說），失敗也不寫停在哪一步。
 */
export const STAGE_NAMES = ["讀取內容", "對應待辦", "檢查規則"] as const;
export const MIN_PLAY_MS = 2000;
/** 每一步亮起的間隔：三步剛好 MIN_PLAY_MS */
export const STAGE_MS = Math.round(MIN_PLAY_MS / STAGE_NAMES.length);
export const SLOW_TEXT = "照片需要久一點，請稍候";
export const WAITING_TEXT = "等待中";
/** 單份處理超過這麼久（毫秒）才追加安撫 */
export const SLOW_AFTER_MS = 8000;

/**
 * 連線中斷（ADR-0027、設計者 11/11）：畫面只寫「連線中斷，上傳失敗」。
 * 背景仍會重新讀取事件確認伺服器有沒有處理好：處理好了就照常顯示結果，不叫旅客重傳而產生重複檔案。
 */
export const INTERRUPTED_LOST = "連線中斷，上傳失敗";
/** 連線中斷後重新讀取事件的次數與間隔（毫秒）：伺服器可能還在處理，給它一點時間 */
export const RECHECK_TRIES = 4;
export const RECHECK_GAP_MS = 3000;

/** 單份檔案的大小上限（與後端 MAX_DOCUMENT_MB 一致） */
export const MAX_DOCUMENT_MB = 10;
const SUPPORTED_EXT = ["pdf", "jpg", "jpeg", "png", "heic", "heif"];

/**
 * 送出前就擋得下的檔案：太大、不支援的類型，直接給明確原因，不送出也不會顯示成「處理中」。
 * HEIC 仍送出（由小助理判斷，檔名旁已註明無法預覽）。
 */
export function precheckFile(file: File): string | undefined {
  if (file.size > MAX_DOCUMENT_MB * 1024 * 1024)
    return `檔案超過 ${MAX_DOCUMENT_MB} MB，請壓縮或改拍小一點再上傳。`;
  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
  if (!SUPPORTED_EXT.includes(ext)) return "這個檔案類型不支援，請改傳 PDF、JPG 或 PNG。";
  return undefined;
}

const SAVED_PENDING = "已先存到你的 Google Drive，等你確認後才算正式";

/** 「已收到，還缺登機證（或改傳一份搭機證明）；…」→「還缺登機證」 */
export function lackText(reason: string | null | undefined): string {
  const first = (reason ?? "").split("；")[0] ?? "";
  return first.replace(/^已收到，/, "").replace(/（.*$/, "") || "還缺其他文件";
}

/** 去掉句尾標點，接在別的句子後面不會變成「。。」 */
const clip = (text: string | null | undefined) => (text ?? "").trim().replace(/[。.\s]+$/, "");

/**
 * 合格結果帶的提醒。「還缺另一份」的 reason 是「缺的說明；提醒」串在一起（6 號 recognizer），
 * 第一段是缺什麼、不是提醒，所以只取後面幾段；其餘結果整個 reason 就是提醒。
 */
function reminderOf(doc: UploadedDocument, lacking: boolean): string {
  if (!lacking) return clip(doc.reason);
  const rest = (doc.reason ?? "").split("；").slice(1).join("；");
  return clip(rest);
}

/**
 * 辨識結果 → 這份文件的標籤與四個階段各自的狀態（規則同設計稿的「情況對照表」，依契約 document_agent.py）。
 * 有沒有存到 Drive 由 `stored` 推得，只寫在標籤裡（「檔案未保留」「沒有存到你的 Google Drive」），說明文字不重複；失敗時不寫停在哪個階段（設計者 11/13）。
 */
export function describeRecognition(doc: UploadedDocument): RecognitionOutcome {
  const reason = clip(doc.reason);
  switch (doc.recognition_status) {
    case "recognized": {
      // 契約保證 recognized 一定有檔案：不看 stored（前後端版本不一致時才不會說謊）
      const lacking = !doc.appended && !doc.todo_complete;
      const reminder = reminderOf(doc, lacking);
      const hasReminder = reminder !== "";
      const kind: RecognitionKind = doc.appended
        ? "appended"
        : lacking
          ? "lack"
          : hasReminder
            ? "remind"
            : "done";
      const text =
        kind === "lack"
          ? `符合規則，${lackText(doc.reason)}`
          : kind === "appended"
            ? "已追加到已完成的待辦"
            : "符合規則，已自動打勾";
      return {
        kind,
        // 提醒是旅客要處理的資訊，不折疊（設計者 11/11）；沒有提醒的合格結果才收進「看全部明細」
        collapsed: !hasReminder,
        hasReminder,
        badge: {
          text: hasReminder ? `${text}（有提醒）` : text,
          tone: hasReminder ? "warn" : "ok",
        },
        note: hasReminder ? `提醒：${reminder}` : undefined,
      };
    }
    case "incomplete": {
      // 缺的欄位名稱與 6 號寫的原因並列（契約：incomplete 的 reason 寫缺什麼），不能只留欄位名稱
      const missingText = doc.missing?.length ? `缺少${doc.missing.join("、")}` : "";
      const lacking =
        missingText && reason && !reason.includes(missingText)
          ? `${missingText}（${reason}）`
          : missingText || reason;
      const next = doc.next_step ? `。下一步：${clip(doc.next_step)}` : "";
      return {
        kind: "incomplete",
        collapsed: false,
        hasReminder: false,
        badge: {
          text: doc.missing?.length
            ? `不合格：缺少${doc.missing.join("、")}（檔案未保留）`
            : "不合格（檔案未保留）",
          tone: "bad",
        },
        note: `${lacking}${next}`,
      };
    }
    case "needs_review":
      // 只有明確的 stored === false 才算沒存；欄位缺少時維持「需要你確認」
      if (doc.stored !== false)
        return {
          kind: "review",
          collapsed: false,
          hasReminder: false,
          badge: { text: "需要你確認", tone: "warn" },
          // 6 號給的原因各不相同（手寫、推測、對不起來…），有就照實顯示，沒有才用固定句
          note: `${reason || "小助理不確定這份對應哪一項待辦，請在下面選一項"}。${SAVED_PENDING}`,
        };
      return {
        kind: "unsaved",
        collapsed: false,
        hasReminder: false,
        badge: { text: "沒有完成：沒有存到你的 Google Drive", tone: "bad" },
        note: `${reason ? `${reason}。` : ""}待辦還沒有勾。下一步：稍後再傳一次，或先授權 Google Drive`,
      };
    case "failed":
      if (doc.failure === "not_matched")
        return {
          kind: "not_matched",
          collapsed: false,
          hasReminder: false,
          badge: { text: "辨識失敗：不在待辦清單中（檔案未保留）", tone: "bad" },
          note: reason || "這份文件不在這次事故的待辦清單中",
        };
      return {
        kind: "unreadable",
        collapsed: false,
        hasReminder: false,
        badge: { text: "無法辨識（檔案未保留）", tone: "bad" },
        note: reason || "小助理看不清楚這份文件，請拍清楚一點再上傳",
      };
    default:
      return {
        kind: "error",
        collapsed: false,
        hasReminder: false,
        badge: { text: "上傳失敗", tone: "bad" },
      };
  }
}

/** 這一列的標籤：還沒有結果時是「等待中」或「處理中」；上傳失敗沒有四階段結果 */
export function rowBadge(row: ProcessingRow): { text: string; tone: Tone } {
  if (row.outcome) return row.outcome.badge;
  if (row.kind === "error") return { text: "上傳失敗", tone: "bad" };
  return { text: row.phase === "run" ? "處理中" : WAITING_TEXT, tone: "wait" };
}

/** 預設不列的：合格的（收在「看全部明細」） */
export const isCollapsed = (row: ProcessingRow) => row.outcome?.collapsed === true;

/**
 * 一批文件的結果摘要（各種結果的份數）：畫面上的摘要列與讀屏的即時通知共用，數字不會對不上。
 * 第一項「已自動打勾」一律列出（可能是 0），其餘有才列。
 * 提醒數寫在各類別的括號裡（規格書 7.3.7 的範例：「6 份已自動打勾（其中 1 份有提醒）」），
 * 通過、追加、還缺另一份只要帶提醒都算。
 */
export function summarizeKinds(
  items: { kind?: RecognitionKind; hasReminder?: boolean }[],
): string[] {
  const of = (k: RecognitionKind[]) => items.filter((x) => x.kind && k.includes(x.kind));
  const withReminder = (k: RecognitionKind[]) => {
    const m = of(k).filter((x) => x.hasReminder).length;
    return m > 0 ? `（其中 ${m} 份有提醒）` : "";
  };
  const line = (k: RecognitionKind[], text: string): [number, string] => [
    of(k).length,
    `${text}${withReminder(k)}`,
  ];
  return [
    line(["done", "remind"], "份已自動打勾"),
    line(["lack"], "份已收到、還缺其他文件"),
    line(["appended"], "份追加到已完成的待辦"),
    line(["review"], "份需要你確認"),
    line(["unsaved"], "份沒有存到 Google Drive"),
    line(["incomplete"], "份不合格"),
    line(["unreadable"], "份無法辨識"),
    line(["not_matched"], "份辨識失敗"),
    line(["error"], "份上傳失敗"),
  ]
    .filter(([n], i) => i === 0 || n > 0)
    .map(([n, t]) => `${n} ${t}`);
}

/**
 * 連線中斷後，從重新讀取的事件找出「這次上傳」進去的文件：只看上傳前就知道的編號之外多出來的那份
 * （伺服器會把檔案改名，比對檔名不可靠）。找不到，或還在 pending，回 undefined。
 */
export function findLandedDocument(
  ctx: IncidentContext,
  known: ReadonlySet<string>,
): UploadedDocument | undefined {
  const doc = (ctx.documents ?? []).find(
    (d) => !known.has(d.id) && d.recognition_status !== "pending",
  );
  if (!doc) return undefined;
  const todo = (ctx.todos ?? []).find((t) => t.id === doc.todo_id);
  return {
    id: doc.id,
    file_name: doc.file_name,
    recognition_status: doc.recognition_status,
    document_kind: doc.document_kind,
    todo_id: doc.todo_id,
    todo_complete: todo?.is_done === true || todo?.status === "done",
    stored: Boolean(doc.storage_path),
  };
}
