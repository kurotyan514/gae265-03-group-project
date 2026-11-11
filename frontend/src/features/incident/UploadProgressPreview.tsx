import { Dialog } from "@base-ui/react/dialog";
import { type ReactNode, useState } from "react";
import { btn, btnSm, lnk } from "../../components/ui/buttons";
import { DialogShell } from "../../components/ui/DialogShell";

/**
 * 處理清單的靜態原型（#290、規格 #287、ADR-0027）：只放在 /dev/ui 給設計者看，正式的 UploadBox 不動。
 * 全部是固定的示意資料：沒有計時器、不連後端；真實的狀態由設計者同意後再接到正式畫面。
 */

type Stage = "ok" | "stop" | "nosave" | "saved" | "unknown" | "skip";
type Tone = "ok" | "warn" | "bad" | "wait";

/** 四個處理階段（GLOSSARY「處理階段」）；只在處理完才顯示各自的真實結果。 */
const STAGE_NAMES = ["認出文件種類", "對應待辦", "檢查內容", "存到你的 Google Drive"] as const;

const STAGE_TEXT: Record<Stage, string> = {
  ok: "通過",
  stop: "停在這裡",
  nosave: "沒有存",
  saved: "已先存（待你確認）",
  unknown: "未確認",
  skip: "未進行",
};

/** 示意縮圖：內嵌 SVG，不放任何真實文件或個資 */
const SAMPLE_IMG =
  "data:image/svg+xml;utf8," +
  encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480" viewBox="0 0 640 480">` +
      `<rect width="640" height="480" fill="#f2f8e7"/>` +
      `<rect x="120" y="50" width="400" height="380" rx="16" fill="#ffffff" stroke="#e2e7dd" stroke-width="4"/>` +
      `<rect x="160" y="100" width="200" height="22" rx="6" fill="#78a817"/>` +
      `<rect x="160" y="150" width="320" height="14" rx="6" fill="#e2e7dd"/>` +
      `<rect x="160" y="184" width="290" height="14" rx="6" fill="#e2e7dd"/>` +
      `<rect x="160" y="218" width="320" height="14" rx="6" fill="#e2e7dd"/>` +
      `<rect x="160" y="252" width="240" height="14" rx="6" fill="#e2e7dd"/>` +
      `<text x="320" y="390" font-size="28" text-anchor="middle" fill="#647364">示意圖片</text>` +
      `</svg>`,
  );

type Preview =
  | { type: "image"; name: string; size: string }
  | { type: "pdf" | "heic"; name: string; size: string };

const TONE_CLASS: Record<Tone, string> = {
  ok: "bg-leaf-soft text-brand",
  warn: "bg-warn-soft text-warn-ink",
  bad: "bg-danger-soft text-danger-ink",
  wait: "bg-paper text-muted",
};

/** 這份檔案的預覽：圖片是縮圖（可點開放大）；PDF 與 HEIC 是圖示加說明 */
function Thumb({ file, onZoom }: { file: Preview; onZoom: (name: string) => void }) {
  if (file.type === "image") {
    return (
      <button
        type="button"
        onClick={() => onZoom(file.name)}
        aria-label={`放大看 ${file.name}`}
        className="size-14 shrink-0 overflow-hidden rounded-tag border border-line bg-paper focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-leaf"
        data-testid="pp-thumb"
      >
        <img src={SAMPLE_IMG} alt="" className="size-full object-cover" />
      </button>
    );
  }
  return (
    <span
      className="inline-grid size-14 shrink-0 place-items-center rounded-tag border border-line bg-paper t-micro font-bold text-muted"
      aria-hidden="true"
      data-testid="pp-icon"
    >
      {file.type === "pdf" ? "PDF" : "HEIC"}
    </span>
  );
}

function Row({
  file,
  badge,
  tone,
  onZoom,
  children,
  testId,
}: {
  file: Preview;
  badge: string;
  tone: Tone;
  onZoom: (name: string) => void;
  children?: ReactNode;
  testId: string;
}) {
  return (
    <li
      className="flex flex-col gap-2 rounded-xl border border-line bg-white px-3.5 py-2.5 t-caption"
      data-testid={testId}
    >
      <div className="flex gap-3">
        <Thumb file={file} onZoom={onZoom} />
        <div className="flex min-w-0 flex-1 flex-col gap-1.5">
          <span className="flex flex-wrap items-center gap-x-2.5 gap-y-1 font-bold text-ink">
            <span className="[overflow-wrap:anywhere]">{file.name}</span>
            <span
              className={`ml-auto rounded-xl px-2.5 py-0.5 text-[13px] leading-5 font-bold ${TONE_CLASS[tone]}`}
              data-testid="pp-badge"
            >
              {badge}
            </span>
          </span>
          <span className="text-[13px] leading-5 text-muted">
            {file.size}
            {file.type === "heic" && (
              <span data-testid="pp-heic-note"> · 無法預覽，但仍會上傳</span>
            )}
          </span>
        </div>
      </div>
      {children}
    </li>
  );
}

/** 處理中：不確定進度，只有一句話；開啟「減少動態」時不轉圈（forceStill 讓設計者在預覽頁直接看到那個樣子） */
function Working({ slow, forceStill }: { slow?: boolean; forceStill?: boolean }) {
  return (
    <span className="flex flex-col gap-1" data-testid="pp-working">
      <span className="inline-flex items-center gap-2 text-[13px] leading-5 font-bold text-heading">
        {!forceStill && (
          <i
            className="size-4 shrink-0 animate-spin rounded-full border-[1.5px] border-leaf border-t-transparent motion-reduce:hidden"
            aria-hidden="true"
            data-testid="pp-spinner"
          />
        )}
        小助理正在處理這份文件…
      </span>
      {slow && (
        <span className="text-[13px] leading-5 text-muted" data-testid="pp-slow">
          照片需要久一點，請稍候
        </span>
      )}
    </span>
  );
}

/** 處理完：四個階段的緊湊小圖示（輔助資訊）；只有停下或沒有存的那一步是紅色 */
function StageTrail({ stages, warn }: { stages: [Stage, Stage, Stage, Stage]; warn?: boolean }) {
  return (
    <ul
      className="m-0 flex list-none flex-wrap gap-x-3 gap-y-1 p-0 text-[13px] leading-5 text-muted"
      data-testid="pp-stages"
    >
      {STAGE_NAMES.map((name, i) => {
        const s = stages[i as 0 | 1 | 2 | 3];
        const good = s === "ok" || s === "saved";
        const bad = s === "stop" || s === "nosave";
        return (
          <li key={name} className="inline-flex items-center gap-1.5" data-testid="pp-stage">
            <i
              className={`inline-grid size-4 shrink-0 place-items-center rounded-full border-[1.5px] text-[10px] not-italic ${
                good
                  ? "border-leaf bg-leaf text-white"
                  : bad
                    ? warn
                      ? "border-warn bg-warn text-white"
                      : "border-coral bg-coral text-white"
                    : "border-line bg-paper"
              }`}
              aria-hidden="true"
            >
              {good ? "✓" : bad ? "✗" : ""}
            </i>
            <span className={bad ? (warn ? "text-warn-ink" : "text-danger-ink") : ""}>
              {name}
              <span className="sr-only">：{STAGE_TEXT[s]}</span>
            </span>
          </li>
        );
      })}
    </ul>
  );
}

/** 同一個意思全頁用同一句話 */
const NOT_SAVED = "這份沒有存到你的 Google Drive";
const SAVED_PENDING = "已先存到你的 Google Drive，等你確認後才算正式";

/** 情況 → 階段、標籤、是否有檔案（依契約 document_agent.py） */
const MAP: [string, string, string, string][] = [
  ["通過（recognized）", "通過、通過、通過、通過", "已處理：通過", "有"],
  ["不合格（incomplete）", "通過、通過、停在這裡、沒有存", "已處理：不合格", "沒有"],
  ["讀不出來（failed）", "停在這裡、未進行、未進行、沒有存", "已處理：讀不出來", "沒有"],
  ["不在待辦（failed）", "通過、停在這裡、未進行、沒有存", "已處理：不在待辦清單", "沒有"],
  [
    "不確定、有授權（needs_review）",
    "通過、停在這裡、未進行、已先存（待你確認）",
    "需要你確認",
    "有（待確認）",
  ],
  [
    "不確定、沒授權或存檔失敗（needs_review）",
    "未確認、未確認、未確認、沒有存",
    "沒有完成：沒有存到你的 Google Drive",
    "沒有",
  ],
];

const jpg = (n: string, size = "2.4 MB"): Preview => ({ type: "image", name: n, size });

type Kind =
  | "done"
  | "lack"
  | "appended"
  | "review"
  | "incomplete"
  | "unreadable"
  | "notmatched"
  | "notdone";

type Result = {
  kind: Kind;
  file: Preview;
  badge: string;
  stages: [Stage, Stage, Stage, Stage];
  /** 一行原因（沒通過的用紅字，需要你確認用琥珀色） */
  reason?: string;
  action?: ReactNode;
};

const PASSED: Kind[] = ["done", "lack", "appended"];
const KIND_TEXT: Record<Kind, string> = {
  done: "已自動打勾",
  lack: "已收到、還缺其他文件",
  appended: "追加到已完成的待辦",
  review: "需要你確認",
  incomplete: "不合格",
  unreadable: "讀不出來",
  notmatched: "不在待辦清單",
  notdone: "沒有完成",
};
const KIND_ORDER = Object.keys(KIND_TEXT) as Kind[];

const NOT_DONE_BADGE = "沒有完成：沒有存到你的 Google Drive";

const MIXED: Result[] = [
  {
    kind: "done",
    file: jpg("延誤證明.jpg"),
    badge: "通過",
    stages: ["ok", "ok", "ok", "ok"],
  },
  {
    kind: "lack",
    file: jpg("登機證.jpg"),
    badge: "通過，還缺機票",
    stages: ["ok", "ok", "ok", "ok"],
    reason: "還缺另一份：機票",
  },
  {
    kind: "appended",
    file: jpg("診斷證明-第二頁.jpg"),
    badge: "已追加到已完成的待辦",
    stages: ["ok", "ok", "ok", "ok"],
  },
  {
    kind: "incomplete",
    file: { type: "pdf", name: "診斷證明.pdf", size: "412 KB" },
    badge: "不合格",
    stages: ["ok", "ok", "stop", "nosave"],
    reason: `停在檢查內容：缺少就診日期。${NOT_SAVED}。下一步：請補上有就診日期的診斷證明再上傳`,
  },
  {
    kind: "review",
    file: jpg("收據.jpg"),
    badge: "需要你確認",
    stages: ["ok", "stop", "skip", "saved"],
    reason: `小助理不確定這份對應哪一項待辦。${SAVED_PENDING}`,
    action: (
      <button type="button" className={`${btnSm} self-start`} data-testid="pp-choose">
        選擇對應的待辦
      </button>
    ),
  },
  {
    kind: "notdone",
    file: jpg("行李證明.jpg"),
    badge: NOT_DONE_BADGE,
    stages: ["unknown", "unknown", "unknown", "nosave"],
    reason: `${NOT_SAVED}：存檔失敗，待辦還沒有勾。下一步：請稍後再傳一次`,
  },
  {
    kind: "notdone",
    file: { type: "pdf", name: "班機延誤證明.pdf", size: "238 KB" },
    badge: NOT_DONE_BADGE,
    stages: ["unknown", "unknown", "unknown", "nosave"],
    reason: `${NOT_SAVED}：還沒有授權，待辦還沒有勾。下一步：先授權，再重新上傳這份`,
    action: (
      <button type="button" className={`${btnSm} self-start`} data-testid="pp-authorize">
        授權 Google Drive
      </button>
    ),
  },
  {
    kind: "unreadable",
    file: jpg("模糊的照片.jpg"),
    badge: "讀不出來",
    stages: ["stop", "skip", "skip", "nosave"],
    reason: `停在認出文件種類：小助理看不清楚這份文件。${NOT_SAVED}。下一步：請拍清楚一點再上傳`,
  },
  {
    kind: "notmatched",
    file: { type: "heic", name: "IMG_0420.HEIC", size: "3.4 MB" },
    badge: "不在待辦清單",
    stages: ["ok", "stop", "skip", "nosave"],
    reason: `停在對應待辦：這份文件不在這次事故的待辦清單中。${NOT_SAVED}`,
  },
];

const ALL_PASS: Result[] = [
  {
    kind: "done",
    file: jpg("延誤證明.jpg"),
    badge: "通過",
    stages: ["ok", "ok", "ok", "ok"],
  },
  {
    kind: "done",
    file: { type: "pdf", name: "班機延誤證明.pdf", size: "238 KB" },
    badge: "通過",
    stages: ["ok", "ok", "ok", "ok"],
  },
];

/**
 * 處理完的清單（設計者的互動原型 upBox）：摘要加「看全部 N 份明細」；預設只列沒通過的，
 * 合格的折疊在明細裡；紅字只給不合格、讀不出來、不在待辦清單、沒有完成；需要你確認是琥珀色。
 * 四個處理階段只是每列下方的輔助小圖示。
 */
function ResultList({
  rows,
  testId,
  onZoom,
}: {
  rows: Result[];
  testId: string;
  onZoom: (name: string) => void;
}) {
  const [showAll, setShowAll] = useState(false);
  const summary = KIND_ORDER.map((k) => [rows.filter((r) => r.kind === k).length, k] as const)
    .filter(([n]) => n > 0)
    .map(([n, k]) => `${n} 份${KIND_TEXT[k]}`)
    .join("、");
  const shown = showAll ? rows : rows.filter((r) => !PASSED.includes(r.kind));
  return (
    <div className="flex flex-col gap-2.5" data-testid={testId}>
      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1.5 t-body text-heading">
        <b>這次上傳 {rows.length} 份：</b>
        <span data-testid="pp-summary">{summary}</span>
        <button
          type="button"
          className={lnk}
          aria-expanded={showAll}
          onClick={() => setShowAll((v) => !v)}
          data-testid="pp-toggle"
        >
          {showAll ? "收合明細" : `看全部 ${rows.length} 份明細`}
        </button>
      </div>
      {/* 有結果時以禮貌的即時通知讓讀屏唸出：「〇〇 已處理：通過」 */}
      <ul className="m-0 flex list-none flex-col gap-2 p-0" aria-live="polite">
        {shown.map((r) => {
          const passed = PASSED.includes(r.kind);
          const tone: Tone = passed ? "ok" : r.kind === "review" ? "warn" : "bad";
          return (
            <Row
              key={`${r.file.name}-${r.kind}`}
              file={r.file}
              badge={r.badge}
              tone={tone}
              onZoom={onZoom}
              testId="pp-res-row"
            >
              {r.reason && (
                <span
                  className={`text-[13px] leading-5 ${
                    tone === "bad"
                      ? "text-danger-ink"
                      : tone === "warn"
                        ? "text-warn-ink"
                        : "text-muted"
                  }`}
                  data-testid="pp-reason"
                >
                  {r.reason}
                </span>
              )}
              <StageTrail stages={r.stages} warn={r.kind === "review"} />
              {r.action}
            </Row>
          );
        })}
      </ul>
    </div>
  );
}

/** 一組示意：外框沿用上傳框（虛線葉綠框），裡面是處理清單 */
function Frame({
  title,
  testId,
  children,
}: {
  title: string;
  testId: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-2" data-testid={testId}>
      <h3 className="m-0 t-label text-heading">{title}</h3>
      <div className="flex flex-col gap-3 rounded-tile border-2 border-dashed border-leaf bg-leaf-soft px-3 py-4 md:px-6 md:py-5">
        {children}
      </div>
    </div>
  );
}

export function UploadProgressPreview() {
  const [zoom, setZoom] = useState<string | null>(null);
  // 關閉動畫期間仍保留最後的檔名，標題與替代文字才不會閃空
  const [lastZoom, setLastZoom] = useState("");
  const openZoom = (name: string) => {
    setLastZoom(name);
    setZoom(name);
  };

  return (
    <section
      className="space-y-5 rounded-2xl border border-line/60 bg-white p-5 shadow-card"
      aria-label="處理清單原型"
      data-testid="pp-root"
    >
      <h2 className="t-section-title text-heading">功能二：處理清單原型（理賠文件上傳）</h2>
      <p className="m-0 t-caption text-muted">
        靜態示意，給設計者看：處理中只有一句不確定進度的話，處理完才顯示四個階段各自的真實結果。不顯示任何階段的輸入或輸出。
      </p>

      <Frame title="1. 處理中：第 1 份處理中，後面的排隊（還沒有結果）" testId="pp-batch">
        <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1.5 t-body text-heading">
          <b>正在處理 3 份文件</b>
          <span className="t-caption text-muted">已完成 0／3</span>
          <span
            className="h-2 basis-full overflow-hidden rounded bg-line"
            role="progressbar"
            aria-label="整批處理進度"
            aria-valuemin={0}
            aria-valuemax={3}
            aria-valuenow={0}
          >
            <i className="block h-full bg-leaf" style={{ width: "0%" }} />
          </span>
        </div>
        <ul className="m-0 flex list-none flex-col gap-2 p-0">
          <Row
            file={jpg("IMG_0412.jpg")}
            badge="處理中"
            tone="wait"
            onZoom={openZoom}
            testId="pp-row"
          >
            <Working />
          </Row>
          <Row
            file={{ type: "pdf", name: "登機證.pdf", size: "186 KB" }}
            badge="等待中"
            tone="wait"
            onZoom={openZoom}
            testId="pp-row"
          />
          <Row
            file={{ type: "heic", name: "IMG_0413.HEIC", size: "3.1 MB" }}
            badge="等待中"
            tone="wait"
            onZoom={openZoom}
            testId="pp-row"
          />
        </ul>
      </Frame>

      <Frame title="2. 處理超過 8 秒：多一句安撫" testId="pp-slow-frame">
        <ul className="m-0 flex list-none flex-col gap-2 p-0">
          <Row
            file={jpg("IMG_0415.jpg", "4.8 MB")}
            badge="處理中"
            tone="wait"
            onZoom={openZoom}
            testId="pp-row"
          >
            <Working slow />
          </Row>
        </ul>
      </Frame>

      <Frame title="3. 開啟「減少動態」：不轉圈，只有文字" testId="pp-reduced">
        <ul className="m-0 flex list-none flex-col gap-2 p-0">
          <Row
            file={jpg("IMG_0416.jpg")}
            badge="處理中"
            tone="wait"
            onZoom={openZoom}
            testId="pp-row"
          >
            <Working forceStill slow />
          </Row>
        </ul>
        <p className="m-0 t-caption text-muted">
          系統設定「減少動態」時，上面各組的轉圈會自動隱藏，只剩文字。
        </p>
      </Frame>

      <Frame
        title="4. 處理完：摘要加沒通過的文件（合格的折疊在「看全部明細」）"
        testId="pp-results"
      >
        <ResultList rows={MIXED} testId="pp-list-mixed" onZoom={openZoom} />
      </Frame>

      <Frame title="4b. 處理完：全部合格時只有摘要" testId="pp-results-pass">
        <ResultList rows={ALL_PASS} testId="pp-list-pass" onZoom={openZoom} />
      </Frame>

      <Frame title="情況對照表（接真實畫面時照這張）" testId="pp-map">
        <ul className="m-0 flex list-none flex-col gap-2 p-0">
          {MAP.map(([c, st, b, f]) => (
            <li
              key={c}
              className="flex flex-col gap-0.5 rounded-xl border border-line bg-white px-3.5 py-2.5 t-caption text-ink"
              data-testid="pp-map-row"
            >
              <b className="[overflow-wrap:anywhere]">{c}</b>
              <span>四個階段：{st}</span>
              <span>標籤：{b}</span>
              <span>Drive 有檔案：{f}</span>
            </li>
          ))}
        </ul>
      </Frame>

      <Frame title="5. 網路中斷與檔案太大" testId="pp-errors">
        <ul className="m-0 flex list-none flex-col gap-2 p-0">
          <Row
            file={jpg("IMG_0421.jpg")}
            badge="連線中斷"
            tone="warn"
            onZoom={openZoom}
            testId="pp-row"
          >
            <span
              className="flex flex-col gap-1 border-l-[3px] border-line pl-2.5 text-[13px] leading-5 text-muted"
              data-testid="pp-offline"
            >
              <span>連線中斷，這份文件可能已經處理好了。</span>
              <span>小助理正在重新讀取確認，請先不要重傳。</span>
            </span>
          </Row>
          <Row
            file={{ type: "pdf", name: "病歷全本.pdf", size: "14.2 MB" }}
            badge="沒有上傳"
            tone="bad"
            onZoom={openZoom}
            testId="pp-row"
          >
            <span className="border-l-[3px] border-line pl-2.5 text-[13px] leading-5 text-muted">
              檔案超過 10 MB，請壓縮或分成兩份再上傳
            </span>
          </Row>
        </ul>
      </Frame>

      <DialogShell
        open={zoom !== null}
        onOpenChange={(o) => !o && setZoom(null)}
        title={lastZoom}
        testId="pp-zoom"
        actions={
          <Dialog.Close className={btn} data-testid="pp-zoom-close">
            關閉
          </Dialog.Close>
        }
      >
        <img
          src={SAMPLE_IMG}
          alt={`${lastZoom} 放大`}
          className="w-full rounded-tile border border-line"
        />
      </DialogShell>
    </section>
  );
}
