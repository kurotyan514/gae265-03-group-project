import { Link } from "@tanstack/react-router";
import { type ReactNode, useState } from "react";
import type { DocumentView, IncidentContext } from "../../client/types.gen";
import { lnk } from "../../components/ui/buttons";
import { FilePickButton } from "../../components/ui/FileDrop";
import { dateOf } from "./IncidentCard";
import { errorText } from "./shared";

/** 上傳回應（POST /incidents/{id}/documents）裡這個畫面用到的欄位。 */
type Uploaded = {
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
};

type Step = "wait" | "run" | "ok" | "bad";
type Kind =
  | "done" // 符合規則，已自動打勾
  | "remind" // 符合規則，附提醒
  | "lack" // 符合規則，還缺另一份
  | "appended" // 追加到已完成的待辦
  | "review" // 需要你確認
  | "incomplete" // 不合格
  | "unreadable" // 無法辨識
  | "not_matched" // 辨識失敗
  | "error"; // 上傳本身失敗（網路、伺服器）

type Row = {
  key: string;
  name: string;
  steps: [Step, Step, Step];
  kind?: Kind;
  /** 判斷依據（結果下面那一行） */
  why?: string;
  /** 還缺什麼（kind 為 lack 時，例：還缺登機證） */
  lack?: string;
  /** 不合格時缺少的欄位（例：延誤期間） */
  missing?: string[];
};

const STEP_NAMES = ["讀取內容", "對應待辦", "檢查規則"] as const;
const STEP_ICON: Record<Step, string> = { wait: "", run: "", ok: "✓", bad: "✗" };
/** 每一步至少顯示多久（毫秒），讓使用者看得到進度；系統設定減少動態時縮短。 */
const STEP_MS = 600;

/** 6 號的結果歸成畫面上的哪一種，以及停在第幾步（0 讀取、1 對應、2 檢查；3 表示全部通過）。 */
function classify(doc: Uploaded): { kind: Kind; failAt: number } {
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
function lackText(reason: string | null | undefined): string {
  const first = (reason ?? "").split("；")[0] ?? "";
  return first.replace(/^已收到，/, "").replace(/（.*$/, "") || "還缺其他文件";
}

function badge(row: Row): { text: string; tone: "ok" | "warn" | "bad" | "wait" } {
  if (!row.kind) {
    const i = row.steps.indexOf("run");
    return { text: i >= 0 ? `${STEP_NAMES[i]}中…` : "等待中", tone: "wait" };
  }
  const text: Record<Kind, string> = {
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
  const ok = ["done", "remind", "lack", "appended"].includes(row.kind);
  return {
    text:
      row.kind === "lack"
        ? `符合規則，${row.lack ?? "還缺其他文件"}`
        : row.kind === "incomplete" && row.missing?.length
          ? `不合格：缺少${row.missing.join("、")}（檔案未保留）`
          : text[row.kind],
    tone: ok ? "ok" : row.kind === "review" ? "warn" : "bad",
  };
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * 2-3i 上傳理賠文件（規格 v3.7、Leon 原型）：可一次選多份，逐份顯示「讀取內容 → 對應待辦 → 檢查規則」，
 * 處理完留下結果與判斷依據；全部處理完收成摘要，先列有問題的檔案。
 *
 * 一次只送一份：同一項待辦的第二份（例如先機票再登機證）要看得到前一份的結果，檔名序號也才不會撞。
 * 動畫只是進度示意：6 號一份處理完才回結果，回來之前停在「讀取內容」。
 */
export function UploadBox({
  id,
  ctx,
  missingCount,
  disabled,
  action,
  onUploaded,
  onStart,
}: {
  id: string;
  ctx: IncidentContext;
  missingCount: number;
  disabled: boolean;
  /** 不能直接選檔時要顯示的按鈕（例如先授權 Google Drive）；有給就取代「上傳理賠文件」 */
  action?: ReactNode;
  onUploaded: (fresh: IncidentContext | null) => void;
  /** 開始處理一批檔案時呼叫（例如清掉頁面上前一次的錯誤訊息） */
  onStart?: () => void;
}) {
  const [rows, setRows] = useState<Row[]>([]);
  const [running, setRunning] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [help, setHelp] = useState(false);

  const todos = ctx.todos ?? [];
  const date = dateOf(ctx);
  const incidentLabel = `${ctx.incident_type_name ?? "這次事故"}${date ? ` · ${date}` : ""}`;

  /** 判斷依據：對應：事故｜待辦｜辨識到：欄位；結果 */
  function why(doc: Uploaded, kind: Kind): string {
    const todo = todos.find((t) => t.id === doc.todo_id);
    const reason = doc.reason ?? "";
    // 不合格：缺什麼，下一行是程式套公式組出的下一步（規格 v3.7 第 5 點）
    if (kind === "incomplete")
      return doc.next_step ? `${reason}\n下一步：${doc.next_step}` : reason;
    if (!todo) return reason;
    const group = todo.scope === "policy" ? "整個行程" : incidentLabel;
    const kindName = doc.document_kind?.replace(/^D\d+\s*/, "");
    const seen = doc.found_fields?.length ? doc.found_fields.join("、") : kindName;
    const base = `對應：${group}｜${todo.title}${seen ? `｜辨識到：${seen}` : ""}`;
    if (kind === "appended") return `${base}；這項待辦已完成，追加為新的一份`;
    if (kind === "lack") return `${base}；${reason.split("；")[0]}`;
    if (kind === "remind") return `${base}；與規則相符。提醒：${reason}`;
    return `${base}；與規則相符`;
  }

  const update = (key: string, patch: Partial<Row>) =>
    setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)));

  async function sendOne(file: File): Promise<Uploaded | { error: string }> {
    const body = new FormData();
    body.append("file", file);
    try {
      const response = await fetch(`/api/v1/incidents/${id}/documents`, { method: "POST", body });
      const data = await response.json().catch(() => null);
      if (!response.ok) return { error: errorText(data, response.status) };
      return data as Uploaded;
    } catch {
      return { error: errorText(undefined) };
    }
  }

  async function run(files: File[]) {
    onStart?.();
    const slow = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? 0.15 : 1;
    const stepMs = STEP_MS * slow;
    const queue: Row[] = files.map((f, i) => ({
      key: `${Date.now()}-${i}`,
      name: f.name,
      steps: ["wait", "wait", "wait"],
    }));
    setRows(queue);
    setShowAll(false);
    setRunning(true);
    for (const [i, file] of files.entries()) {
      const key = queue[i]?.key ?? "";
      update(key, { steps: ["run", "wait", "wait"] });
      const [result] = await Promise.all([sendOne(file), sleep(stepMs)]);
      if ("error" in result) {
        update(key, { steps: ["bad", "wait", "wait"], kind: "error", why: result.error });
        continue;
      }
      const { kind, failAt } = classify(result);
      const steps: [Step, Step, Step] = ["run", "wait", "wait"];
      for (let s = 0; s < 3; s++) {
        if (s === failAt) {
          steps[s] = "bad";
          break;
        }
        steps[s] = "ok";
        if (s < 2) {
          steps[s + 1] = "run";
          update(key, { steps: [...steps] as [Step, Step, Step] });
          await sleep(stepMs);
        }
      }
      update(key, {
        steps: [...steps] as [Step, Step, Step],
        kind,
        why: why(result, kind),
        lack: kind === "lack" ? lackText(result.reason) : undefined,
        missing: result.missing,
      });
    }
    setRunning(false);
    // 重新讀事件：6 號可能勾選了待辦
    try {
      const fresh = await fetch(`/api/v1/incidents/${id}`);
      onUploaded(fresh.ok ? ((await fresh.json()) as IncidentContext) : null);
    } catch {
      onUploaded(null);
    }
  }

  const doneCount = rows.filter((r) => r.kind).length;
  const count = (k: Kind[]) => rows.filter((r) => r.kind && k.includes(r.kind)).length;
  const summary = [
    [count(["done", "remind"]), "份已自動打勾"],
    [count(["remind"]), "份有提醒"],
    [count(["lack"]), "份已收到、還缺其他文件"],
    [count(["appended"]), "份追加到已完成的待辦"],
    [count(["review"]), "份需要你確認"],
    [count(["incomplete"]), "份不合格"],
    [count(["unreadable"]), "份無法辨識"],
    [count(["not_matched"]), "份辨識失敗"],
    [count(["error"]), "份上傳失敗"],
  ]
    .filter(([n], i) => i === 0 || (n as number) > 0)
    .map(([n, t]) => `${n} ${t}`);
  // 摘要預設只列要注意的：完全沒問題的（打勾且沒有提醒）收在「看全部明細」
  const shown = showAll ? rows : rows.filter((r) => r.kind !== "done");

  return (
    <div
      className="flex flex-col gap-3 rounded-tile border-2 border-dashed border-leaf bg-leaf-soft px-6 py-5"
      data-testid="upload-box"
    >
      <div className="flex flex-wrap items-center gap-3.5">
        {action ?? (
          <FilePickButton
            label={running ? "處理中…" : "上傳理賠文件"}
            accept=".pdf,.jpg,.jpeg,.png"
            multiple
            disabled={disabled || running}
            onFiles={(files) => void run(files)}
            inputTestId="doc-file"
            primary
          />
        )}
        <span className="t-caption text-muted">
          {running
            ? "處理中，待辦與問答可照常使用"
            : missingCount > 0
              ? `還缺 ${missingCount} 份 · 可一次選多份`
              : "文件都已備齊，仍可追加"}
        </span>
        <span className="relative ml-auto">
          <button
            type="button"
            className="inline-grid size-7 place-items-center rounded-full border border-leaf bg-white font-bold text-brand"
            aria-label="上傳說明"
            aria-expanded={help}
            onClick={() => setHelp((v) => !v)}
            data-testid="upload-help-toggle"
          >
            ?
          </button>
          {/* 點了才展開：手機沒有「滑鼠移過去」 */}
          {help && (
            <span
              role="note"
              className="absolute top-9 right-[-6px] z-10 block w-[min(280px,80vw)] rounded-xl bg-heading px-3.5 py-3 text-left t-caption font-normal text-white shadow-lg"
            >
              可一次選多份，手機可直接拍照；PDF、JPG、PNG，每份 10 MB 內。上傳後會逐份「讀取內容 →
              對應待辦 →
              檢查規則」，通過的自動打勾；檔案依「事故類型_待辦名稱_序號」重新命名，存在你的 Google
              Drive，送件時作為附件。
            </span>
          )}
        </span>
      </div>

      {rows.length > 0 && (
        <div
          className="flex flex-col gap-2.5 rounded-2xl border border-line bg-white p-4"
          role="status"
          data-testid="upload-progress"
        >
          {running ? (
            <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1.5 t-body text-heading">
              <b>正在處理 {rows.length} 份文件</b>
              <span className="t-caption text-muted">
                已完成 {doneCount}／{rows.length}
              </span>
              <span
                className="h-2 basis-full overflow-hidden rounded bg-line"
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={rows.length}
                aria-valuenow={doneCount}
              >
                <i
                  className="block h-full bg-leaf transition-[width] duration-300"
                  style={{ width: `${(doneCount / rows.length) * 100}%` }}
                />
              </span>
            </div>
          ) : (
            <div
              className="flex flex-wrap items-center gap-x-2.5 gap-y-1.5 t-body text-heading"
              data-testid="upload-summary"
            >
              <b>這次上傳 {rows.length} 份：</b>
              <span>{summary.join("、")}</span>
              <button
                type="button"
                className={lnk}
                aria-expanded={showAll}
                onClick={() => setShowAll((v) => !v)}
                data-testid="upload-detail-toggle"
              >
                {showAll ? "收合明細" : `看全部 ${rows.length} 份明細`}
              </button>
            </div>
          )}
          {(running ? rows : shown).length > 0 && (
            <ul className="m-0 flex list-none flex-col gap-2 p-0">
              {(running ? rows : shown).map((r) => {
                const b = badge(r);
                return (
                  <li
                    key={r.key}
                    className="flex flex-col gap-1.5 rounded-xl border border-line bg-white px-3.5 py-2.5 t-caption"
                    data-testid="upload-row"
                  >
                    <span className="flex flex-wrap items-center gap-x-2.5 gap-y-1 font-bold text-ink">
                      <span className="[overflow-wrap:anywhere]">📄 {r.name}</span>
                      <span
                        className={`ml-auto rounded-xl px-2.5 py-0.5 text-[13px] leading-5 font-bold ${
                          b.tone === "ok"
                            ? "bg-leaf-soft text-brand"
                            : b.tone === "warn"
                              ? "bg-warn-soft text-warn-ink"
                              : b.tone === "bad"
                                ? "bg-danger-soft text-danger-ink"
                                : "bg-paper text-muted"
                        }`}
                        data-testid="upload-result"
                      >
                        {b.text}
                      </span>
                    </span>
                    {r.kind ? (
                      r.why && (
                        <span className="whitespace-pre-line border-l-[3px] border-line pl-2.5 text-[13px] leading-5 text-muted">
                          {r.why}
                          {r.kind === "review" && (
                            <>
                              {" "}
                              <Link
                                to="/incident/$id/documents"
                                params={{ id }}
                                className="font-bold text-leaf-text underline"
                              >
                                選擇對應的待辦
                              </Link>
                            </>
                          )}
                        </span>
                      )
                    ) : (
                      <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] text-muted">
                        {STEP_NAMES.map((n, i) => (
                          <span key={n} className="contents">
                            {i > 0 && <span className="text-line">→</span>}
                            <span
                              className={`inline-flex items-center gap-1.5 whitespace-nowrap ${
                                r.steps[i] === "run" ? "font-bold text-heading" : ""
                              }`}
                            >
                              <i
                                className={`inline-grid size-[18px] place-items-center rounded-full border-[1.5px] text-[11px] not-italic ${
                                  r.steps[i] === "run"
                                    ? "animate-spin border-leaf border-t-transparent"
                                    : r.steps[i] === "ok"
                                      ? "border-leaf bg-leaf text-white"
                                      : r.steps[i] === "bad"
                                        ? "border-coral bg-coral text-white"
                                        : "border-line bg-paper"
                                }`}
                              >
                                {STEP_ICON[r.steps[i] ?? "wait"]}
                              </i>
                              {n}
                            </span>
                          </span>
                        ))}
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
