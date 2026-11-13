import { type ReactNode, useEffect, useId, useRef, useState } from "react";
import { recheckIncidentDocument, rejectIncidentDocument } from "../../client";
import type { IncidentContext } from "../../client/types.gen";
import { btnSm, lnk } from "../../components/ui/buttons";
import { FilePickButton } from "../../components/ui/FileDrop";
import { dateOf } from "./IncidentCard";
import { errorText } from "./shared";
import { type FilePreview, makePreview, ZoomDialog } from "./UploadPreview";
import { STOP, UploadProcessingRow, WorkingNote } from "./UploadProcessingRow";
import {
  describeRecognition,
  findLandedDocument,
  INTERRUPTED_LOST,
  isCollapsed,
  type RecognitionKind as Kind,
  MIN_PLAY_MS,
  precheckFile,
  RECHECK_GAP_MS,
  RECHECK_TRIES,
  type ProcessingRow as Row,
  STAGE_MS,
  STAGE_NAMES,
  summarizeKinds,
  type UploadedDocument as Uploaded,
} from "./uploadRecognition";

/** 「都不是」在選單裡的值 */
const NONE = "__none__";

/**
 * 2-3i 上傳理賠文件（規格 v3.7、ADR-0027）：可一次選多份，依序處理。
 * 處理中逐步亮起「讀取內容 → 對應待辦 → 檢查規則」（設計者 11/13），最短 MIN_PLAY_MS 演完、每份只演一次，
 * 排在後面的標「等待中」；6 號一份處理完才回結果，回來後才顯示結果，結果裡不留階段。
 * 全部處理完收成摘要，預設只列沒通過的文件，合格的收在「看全部明細」。
 *
 * 一次只送一份：同一項待辦的第二份（例如先機票再登機證）要看得到前一份的結果，檔名序號也才不會撞。
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
  /** 這一次上傳的預覽（只在瀏覽器；key 對應處理列），新一批開始與離開頁面時 revoke */
  const [previews, setPreviews] = useState<Record<string, FilePreview>>({});
  const [zoomKey, setZoomKey] = useState<string | null>(null);
  const urls = useRef<string[]>([]);
  const revokeAll = () => {
    for (const u of urls.current) URL.revokeObjectURL(u);
    urls.current = [];
  };
  useEffect(
    () => () => {
      for (const u of urls.current) URL.revokeObjectURL(u);
    },
    [],
  );

  const todos = ctx.todos ?? [];
  // 一批文件處理要很久，期間待辦可能被改（使用者手動勾、6 號勾選）：判斷依據每份處理完時讀最新的，不讀批次開始時的快照
  const todosRef = useRef(todos);
  todosRef.current = todos;
  /** 事件裡目前已有的文件編號：連線中斷時用來判斷「這次上傳」有沒有進去 */
  const docIdsRef = useRef<string[]>([]);
  docIdsRef.current = (ctx.documents ?? []).map((d) => d.id);
  const date = dateOf(ctx);
  const incidentLabel = `${ctx.incident_type_name ?? "這次事故"}${date ? ` · ${date}` : ""}`;
  const listId = useId();
  /** 給讀屏的狀態：整批處理完才念一次摘要（含被折疊的合格列與上傳失敗），避免連續完成時前一份被後一份蓋掉 */
  const [announce, setAnnounce] = useState("");

  /** 判斷依據：對應：事故｜待辦｜辨識到：欄位名稱（只有名稱，不含文件內容）；沒有對應到待辦就沒有 */
  function basisOf(doc: Uploaded, kind: Kind): string | undefined {
    const todo = todosRef.current.find((t) => t.id === doc.todo_id);
    if (!todo) return undefined;
    const group = todo.scope === "policy" ? "整個行程" : incidentLabel;
    const kindName = doc.document_kind?.replace(/^D\d+\s*/, "");
    const seen = doc.found_fields?.length ? doc.found_fields.join("、") : kindName;
    const base = `對應：${group}｜${todo.title}${seen ? `｜辨識到：${seen}` : ""}`;
    if (kind === "appended") return `${base}；這項待辦已完成，追加為新的一份`;
    if (kind === "done" || kind === "remind" || kind === "lack") return `${base}；與規則相符`;
    return base;
  }

  const update = (key: string, patch: Partial<Row>) =>
    setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)));

  /** 把這一列的階段亮一遍：每 STAGE_MS 前進一步，停在最後一步（轉圈）等結果；回傳的 promise 在 MIN_PLAY_MS 後結束 */
  function playStages(key: string): Promise<void> {
    update(key, { stage: 0 });
    for (let i = 1; i < STAGE_NAMES.length; i++)
      setTimeout(() => update(key, { stage: i }), i * STAGE_MS);
    return new Promise((resolve) => setTimeout(resolve, MIN_PLAY_MS));
  }

  /** 不設前端逾時：處理要多久就等多久。fetch 本身丟錯才是連線中斷（伺服器可能已處理完）。 */
  async function sendOne(
    file: File,
  ): Promise<Uploaded | { error: string } | { interrupted: true }> {
    const body = new FormData();
    body.append("file", file);
    try {
      const response = await fetch(`/api/v1/incidents/${id}/documents`, { method: "POST", body });
      const data = await response.json().catch(() => null);
      if (!response.ok) return { error: errorText(data, response.status) };
      return data as Uploaded;
    } catch {
      return { interrupted: true };
    }
  }

  /** 連線中斷：重新讀事件幾次，看這次上傳有沒有進去（不叫旅客盲目重傳）；找到就回那份，沒有就回 undefined */
  async function recheckAfterInterrupt(known: Set<string>): Promise<Uploaded | undefined> {
    for (let i = 0; i < RECHECK_TRIES; i++) {
      if (i > 0) await new Promise((resolve) => setTimeout(resolve, RECHECK_GAP_MS));
      try {
        const res = await fetch(`/api/v1/incidents/${id}`);
        if (!res.ok) continue;
        const landed = findLandedDocument((await res.json()) as IncidentContext, known);
        if (landed) return landed;
      } catch {
        // 還連不上：下一輪再試
      }
    }
    return undefined;
  }

  /** 6 號的結果：套到這一列（標籤、四個階段、說明） */
  function finish(key: string, result: Uploaded) {
    const outcome = describeRecognition(result);
    update(key, {
      basis: basisOf(result, outcome.kind),
      phase: "done",
      kind: outcome.kind,
      outcome,
      error: undefined,
      docId: result.id,
      candidates: result.candidate_todo_ids ?? [],
      choice: undefined,
      expanded: false,
      busy: false,
    });
    return outcome;
  }

  async function run(files: File[]) {
    onStart?.();
    revokeAll();
    const made = files.map(makePreview);
    urls.current = made.flatMap((p) => (p.url ? [p.url] : []));
    const queue: Row[] = files.map((f, i) => ({
      key: `${Date.now()}-${i}`,
      name: f.name,
      phase: "wait",
    }));
    setRows(queue);
    setPreviews(Object.fromEntries(queue.map((q, i) => [q.key, made[i] as FilePreview])));
    setZoomKey(null);
    setShowAll(false);
    setRunning(true);
    setAnnounce(`開始處理 ${files.length} 份文件`);
    const kinds: { kind?: Kind; hasReminder?: boolean }[] = [];
    // 這一批上傳前與上傳中已知的文件編號：連線中斷後，多出來的那份就是這次的
    const known = new Set(docIdsRef.current);
    for (const [i, file] of files.entries()) {
      const key = queue[i]?.key ?? "";
      const refused = precheckFile(file);
      if (refused) {
        update(key, { phase: "done", kind: "error", error: refused });
        kinds.push({ kind: "error" });
        continue;
      }
      update(key, { phase: "run" });
      // 結果最快也要等階段演完；演過就不重演（結果出來後整列換成標籤）
      const played = playStages(key);
      let result = await sendOne(file);
      if ("interrupted" in result) {
        // 重新讀取期間仍是「處理中」；處理好了就照常顯示結果，沒有才是「連線中斷，上傳失敗」
        const landed = await recheckAfterInterrupt(known);
        if (!landed) result = { error: INTERRUPTED_LOST };
        else {
          known.add(landed.id ?? "");
          await played;
          kinds.push(finish(key, landed));
          continue;
        }
      }
      await played;
      if ("error" in result) {
        update(key, { phase: "done", kind: "error", error: result.error });
        kinds.push({ kind: "error" });
      } else {
        if (result.id) known.add(result.id);
        kinds.push(finish(key, result));
      }
    }
    setRunning(false);
    setAnnounce(`上傳完成，共 ${files.length} 份：${summarizeKinds(kinds).join("、")}`);
    await refresh();
  }

  /** 重新讀事件：6 號可能勾選了待辦 */
  async function refresh() {
    try {
      const fresh = await fetch(`/api/v1/incidents/${id}`);
      onUploaded(fresh.ok ? ((await fresh.json()) as IncidentContext) : null);
    } catch {
      onUploaded(null);
    }
  }

  /** 需要你確認：選了待辦就請 6 號依那項再檢查一次；選「都不是」就當辨識失敗、刪掉檔案（規格 v3.7 第 3 點） */
  async function decide(row: Row) {
    if (!row.docId || !row.choice) return;
    update(row.key, { busy: true });
    if (row.choice === NONE) {
      const res = await rejectIncidentDocument({
        path: { incident_id: id, document_id: row.docId },
      });
      if (!res.data) {
        update(row.key, { busy: false, error: errorText(res.error, res.response?.status) });
        return;
      }
      const outcome = finish(row.key, {
        file_name: row.name,
        recognition_status: "failed",
        failure: "not_matched",
        reason: "你選了「都不是」，這份檔案沒有保留",
        stored: false,
      });
      setAnnounce(`${row.name} ${outcome.badge.text}`);
      onUploaded(res.data);
      return;
    }
    void playStages(row.key);
    update(row.key, {
      phase: "run",
      kind: undefined,
      outcome: undefined,
      basis: undefined,
      error: undefined,
    });
    const res = await recheckIncidentDocument({
      path: { incident_id: id, document_id: row.docId },
      body: { todo_id: row.choice },
    });
    if (!res.data) {
      // 沒檢查成：回到「需要你確認」，使用者可以再試
      update(row.key, {
        phase: "done",
        kind: row.kind,
        outcome: row.outcome,
        basis: row.basis,
        error: errorText(res.error, res.response?.status),
        busy: false,
      });
      return;
    }
    const outcome = finish(row.key, res.data as Uploaded);
    setAnnounce(`${row.name} ${outcome.badge.text}`);
    await refresh();
  }

  /** 選單的選項：先列 6 號認為可能的；沒有候選或按了「看全部」就列所有還缺文件的待辦 */
  function choices(row: Row) {
    const open = todos.filter((t) => t.requires_upload && !t.is_done && t.applicable !== false);
    const candidates = (row.candidates ?? [])
      .map((cid) => todos.find((t) => t.id === cid))
      .filter((t) => t !== undefined);
    if (candidates.length === 0 || row.expanded) {
      const rest = open.filter((t) => !candidates.some((c) => c.id === t.id));
      return { list: [...candidates, ...rest], canExpand: false };
    }
    return { list: candidates, canExpand: open.some((t) => !candidates.includes(t)) };
  }

  const doneCount = rows.filter((r) => r.phase === "done").length;
  // 等使用者選的時候，上傳鈕鎖住（規格 v3.7 第 3 點）
  const waiting = !running && rows.some((r) => r.kind === "review" && r.docId);
  const summary = summarizeKinds(
    rows.map((r) => ({ kind: r.kind, hasReminder: r.outcome?.hasReminder })),
  );
  // 摘要預設只列沒通過的；合格的（通過、追加、還缺另一份）收在「看全部明細」
  const shown = showAll ? rows : rows.filter((r) => !isCollapsed(r));

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
            disabled={disabled || running || waiting}
            onFiles={(files) => void run(files)}
            inputTestId="doc-file"
            primary
          />
        )}
        <span className="t-caption text-muted">
          {running
            ? "處理中，待辦與問答可照常使用"
            : waiting
              ? "請先替「需要你確認」的檔案選擇對應的待辦"
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
              可一次選多份，手機可直接拍照；PDF、JPG、PNG，每份 10 MB 內。上傳後小助理會逐份處理，
              通過的自動打勾；檔案依「事故類型_待辦名稱_序號」重新命名，存在你的 Google
              Drive，送件時作為附件。
            </span>
          )}
        </span>
      </div>

      {rows.length > 0 && (
        <div
          className="flex flex-col gap-2.5 rounded-2xl border border-line bg-white p-4"
          data-testid="upload-progress"
        >
          <p role="status" className="sr-only" data-testid="upload-announce">
            {announce}
          </p>
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
                className={btnSm}
                aria-expanded={showAll}
                aria-controls={listId}
                onClick={() => setShowAll((v) => !v)}
                data-testid="upload-detail-toggle"
              >
                {showAll ? "收合明細" : `看全部 ${rows.length} 份明細`}
              </button>
            </div>
          )}
          <ul
            id={listId}
            className="m-0 flex list-none flex-col gap-2 p-0"
            hidden={(running ? rows : shown).length === 0}
          >
            {(running ? rows : shown).map((r) => (
              <UploadProcessingRow
                key={r.key}
                row={r}
                preview={previews[r.key]}
                onZoom={() => setZoomKey(r.key)}
              >
                {r.phase === "run" && <WorkingNote stage={r.stage} />}
                {r.error && (
                  <span className="whitespace-pre-line border-l-[3px] border-line pl-2.5 text-[13px] leading-5 text-danger-ink">
                    {r.error}
                  </span>
                )}
                {r.outcome?.note && (
                  <span
                    className={`border-l-[3px] border-line pl-2.5 text-[13px] leading-5 ${
                      r.outcome.badge.tone === "bad" || r.outcome.badge.tone === "warn"
                        ? STOP[r.outcome.badge.tone].text
                        : "text-muted"
                    }`}
                    data-testid="upload-note"
                  >
                    {r.outcome.note}
                  </span>
                )}
                {r.basis && (
                  <span className="text-[13px] leading-5 text-muted" data-testid="upload-basis">
                    {r.basis}
                  </span>
                )}
                {r.kind === "review" && r.docId && r.phase === "done" && !running && (
                  <Chooser
                    row={r}
                    options={choices(r)}
                    onChange={(patch) => update(r.key, patch)}
                    onSubmit={() => void decide(r)}
                  />
                )}
              </UploadProcessingRow>
            ))}
          </ul>
          <ZoomDialog
            zoom={
              zoomKey && previews[zoomKey]?.url
                ? {
                    name: rows.find((r) => r.key === zoomKey)?.name ?? "",
                    url: previews[zoomKey].url,
                  }
                : null
            }
            onClose={() => setZoomKey(null)}
          />
        </div>
      )}
    </div>
  );
}

/**
 * 需要你確認：選這份檔案對應哪一項待辦（規格 v3.7 第 3 點）。
 * 先列 6 號認為可能的那幾項，「看全部」展開所有還缺文件的待辦，另外有「都不是」。
 */
function Chooser({
  row,
  options,
  onChange,
  onSubmit,
}: {
  row: Row;
  options: { list: { id: string; title: string }[]; canExpand: boolean };
  onChange: (patch: Partial<Row>) => void;
  onSubmit: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="upload-chooser">
      <select
        aria-label={`${row.name} 對應的待辦`}
        value={row.choice ?? ""}
        onChange={(e) => onChange({ choice: e.target.value })}
        disabled={row.busy}
        className="max-w-full rounded-tag border border-line bg-white px-2.5 py-2 t-caption md:max-w-[320px]"
      >
        <option value="">選擇對應的待辦</option>
        {options.list.map((t) => (
          <option key={t.id} value={t.id}>
            {t.title}
          </option>
        ))}
        <option value={NONE}>都不是</option>
      </select>
      {options.canExpand && (
        <button
          type="button"
          className={lnk}
          onClick={() => onChange({ expanded: true })}
          data-testid="chooser-show-all"
        >
          看全部
        </button>
      )}
      <button
        type="button"
        className={btnSm}
        disabled={row.busy || !row.choice}
        onClick={onSubmit}
        data-testid="chooser-submit"
      >
        {row.busy ? "檢查中…" : row.choice === NONE ? "確定都不是" : "確認是這一項"}
      </button>
    </div>
  );
}
