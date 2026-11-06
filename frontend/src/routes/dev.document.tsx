import { Button } from "@base-ui/react/button";
import { createFileRoute } from "@tanstack/react-router";
import { type ChangeEvent, type ReactNode, useEffect, useRef, useState } from "react";
import { listDocumentSamples } from "../client";
import type { DocumentSampleOut, StepField, WalkStep, WalkthroughOut } from "../client/types.gen";

export const Route = createFileRoute("/dev/document")({
  component: DocumentWalkthroughPage,
});

const box = "space-y-3 rounded-md border p-3";
const primary = "rounded-md bg-gray-900 px-3 py-1 text-white disabled:opacity-50";
const secondary = "rounded-md border px-3 py-1 hover:bg-gray-100 disabled:opacity-50";
const small = "rounded-md border px-2 py-0.5 text-xs hover:bg-gray-100 disabled:opacity-50";

const STATE_STYLE: Record<WalkStep["state"], { label: string; className: string }> = {
  ok: { label: "完成", className: "border-green-300 bg-green-50 text-green-900" },
  warn: { label: "要使用者確認", className: "border-amber-300 bg-amber-50 text-amber-900" },
  fail: { label: "停在這一步", className: "border-red-300 bg-red-50 text-red-900" },
  skip: { label: "沒有執行", className: "border-gray-200 bg-gray-50 text-gray-500" },
};

const RESULT_STYLE: Record<WalkthroughOut["status"], string> = {
  recognized: "border-green-400 bg-green-50",
  needs_review: "border-amber-400 bg-amber-50",
  incomplete: "border-orange-400 bg-orange-50",
  failed: "border-red-400 bg-red-50",
};

const REPO = "https://github.com/kurotyan514/gae265-03-group-project";
const CODE = `${REPO}/blob/feat/agent-6-document/backend/app/agents/document`;
const ADR = `${REPO}/blob/feat/agent-6-document/docs/adr`;
const issue = (n: number) => `${REPO}/issues/${n}`;

/** 每一步用了什麼技術、程式放在後端哪裡、對應的 ticket（固定說明；這次的輸入輸出由後端回傳）。 */
type StepInfoData = {
  tech: string;
  code: { file: string; fn: string }[];
  tickets: number[];
  docs?: { label: string; href: string }[];
};
const STEP_INFO: Record<string, StepInfoData | undefined> = {
  read: {
    tech: "電子 PDF：PyMuPDF 直接讀文字層（不送外部服務）；照片或掃描檔：Azure AI Document Intelligence（prebuilt-read，REST）",
    code: [{ file: "reader.py", fn: "read_document()、AzureDocumentIntelligence" }],
    tickets: [67],
    docs: [
      { label: "ADR-0022", href: `${ADR}/0022-document-ocr-with-azure-document-intelligence.md` },
    ],
  },
  privacy: {
    tech: "Python 正規表示式：共用的去識別化規則，加上 6 號補的標籤、拆行姓名、英文姓名、手寫申請書的姓名與地址",
    code: [
      { file: "privacy.py", fn: "deidentify_document_text()" },
      { file: "../../policy/deidentify.py", fn: "共用規則 deidentify_text()" },
    ],
    tickets: [65],
    docs: [{ label: "ADR-0009", href: `${ADR}/0009-policy-document-personal-data.md` }],
  },
  classify: {
    tech: "關鍵字計分，由程式判斷（不用 LLM）；同分或沒命中就當成「不確定」交給使用者",
    code: [{ file: "codes.py", fn: "classify()、SPECS" }],
    tickets: [66],
    docs: [
      { label: "ADR-0004", href: `${ADR}/0004-llm-never-produces-numbers.md` },
      { label: "ADR-0011", href: `${ADR}/0011-claim-flow-bounded-llm-judgement.md` },
    ],
  },
  match: {
    tech: "用文件代碼找事件裡的待辦；平台還沒給 document_code 前，用待辦標題的關鍵字暫代",
    code: [{ file: "codes.py", fn: "matching_todos()" }],
    tickets: [66, 71],
  },
  check: {
    tech: "合格規範逐欄檢查：qualification_rules.json 的正規表示式，每條規則都要有出處；使用者確認過（verified）才生效",
    code: [
      { file: "rules.py", fn: "check()、load_rules()" },
      { file: "qualification_rules.json", fn: "規則內容" },
    ],
    tickets: [69],
  },
  save: {
    tech: "Google Drive API（drive.file 權限，httpx 呼叫 REST）；測試台用假雲端 DevFakeDrive，不會真的存檔",
    code: [{ file: "storage.py", fn: "GoogleDrive、DevFakeDrive、document_file_name()" }],
    tickets: [70],
  },
  complete: {
    tech: "完成條件由程式判斷：D02 要機票＋登機證兩份，或一份搭機證明；其他文件一份就完成",
    code: [
      { file: "codes.py", fn: "completion()" },
      { file: "recognizer.py", fn: "DocumentAgent.recognize()（串起全部步驟）" },
    ],
    tickets: [66, 36],
  },
};

// 展示用的事件與待辦，跟後端 walkthrough.py 的 SAMPLE_TODOS 一致；分組照原型 2-3（依事故，理賠申請書放「整個行程」）
const TRIP_LINE = "日本 2026/07/05～07/10 · 富邦 進階型（展示）";
const D02 = "機票及登機證，或航空業者出具的搭機證明";
type TodoGroup = { label: string; todos: { title: string; note?: string }[] };
// 照原型 2-3：待辦分「事故當下」「回國後整理」，裡面再依事故分組（待辦的 phase：on_site／after_return）
const PHASES: { label: string; groups: TodoGroup[] }[] = [
  {
    label: "事故當下",
    groups: [
      {
        label: "班機延誤 · 2026/07/10",
        todos: [
          { title: "請航空公司開立班機延誤／取消證明", note: "需載明原定與實際起飛時間及原因" },
          { title: D02, note: "機票和登機證兩份都要；也可以改交航空業者出具的搭機證明" },
        ],
      },
    ],
  },
  {
    label: "回國後整理",
    groups: [
      {
        label: "整個行程",
        todos: [{ title: "填寫理賠申請書", note: "紙本填寫後，和所有文件一起寄出" }],
      },
    ],
  },
];
const TODO_GROUPS = PHASES.flatMap((p) => p.groups);
const ALL_TODOS = TODO_GROUPS.flatMap((g) => g.todos);
const groupOf = (todo: string) =>
  TODO_GROUPS.find((g) => g.todos.some((t) => t.title === todo))?.label ?? "";

/** 掛在待辦上的一份已通過文件。kind 是 6 號認出的種類（例如「D02 登機證」），file 是存檔的檔名。 */
type Filed = { id: number; todo: string; kind: string; file: string };
/** 一次上傳：辨識結果與你選的檔案預覽（blob 網址，只在瀏覽器裡）。 */
type Upload = {
  id: number;
  label: string;
  preview: { url: string; isPdf: boolean };
  result: WalkthroughOut | null;
  error: string | null;
  // 從哪一項待辦的「上傳」按鈕傳的；沒有就是從上傳區
  from?: string;
};

/** 刪掉檔案後重算完成條件：機票＋登機證兩份都要，或一份搭機證明；其他待辦一份就完成（原型 R8）。 */
function isComplete(todo: string, kinds: string[]): boolean {
  if (todo !== D02) return kinds.length > 0;
  const has = (k: string) => kinds.some((x) => x.endsWith(k));
  return has("搭機證明") || (has("機票") && has("登機證"));
}

/** 機票／登機證只交了一份時的提示，文字照原型。 */
function lackOf(todo: string, kinds: string[]): string | null {
  if (todo !== D02 || !kinds.length || isComplete(todo, kinds)) return null;
  const miss = ["機票", "登機證"].filter((k) => !kinds.some((x) => x.endsWith(k)));
  return `還差${miss.join("、")}，也可改交搭機證明`;
}

const baseName = (path: string) => path.split("/").pop() ?? path;

/** 後端錯誤訊息（FastAPI 的 detail）轉成一行字。 */
function detailOf(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  return typeof detail === "string" ? `${status} ${detail}` : `HTTP ${status}`;
}

/**
 * 文件辨識測試台，版面照原型 2-4「上傳理賠文件」：待辦依事故分組、選擇檔案、辨識結果。
 * 每份文件都用 6 號真正的程式辨識，下面可以一步一步看它怎麼辨識的。
 * Drive 是展示用的假雲端，檔案不會存到任何地方；畫面上的文字都已經遮過個資。
 */
function DocumentWalkthroughPage() {
  const [samples, setSamples] = useState<DocumentSampleOut[]>([]);
  const [hasGrant, setHasGrant] = useState(true);
  const [draftRules, setDraftRules] = useState(false);
  const [filed, setFiled] = useState<Filed[]>([]);
  const [done, setDone] = useState<Record<string, boolean>>({});
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [currentId, setCurrentId] = useState<number | null>(null);
  const [shown, setShown] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 連續上傳多份時，下一份要知道前一份已經通過（previous），所以用 ref 存最新的清單
  const filedRef = useRef<Filed[]>([]);
  // 按「下一步」後，把新出現的那一步捲到看得到的地方
  const lastStepRef = useRef<HTMLLIElement>(null);
  const nextId = useRef(1);
  const urls = useRef<string[]>([]);
  const pickerRef = useRef<HTMLInputElement>(null);
  const dropRef = useRef<HTMLElement>(null);
  const uploadFrom = useRef<string | undefined>(undefined);
  const [dragging, setDragging] = useState(false);
  const [zoom, setZoom] = useState<Upload | null>(null);

  useEffect(
    () => () => {
      for (const u of urls.current) URL.revokeObjectURL(u);
    },
    [],
  );

  useEffect(() => {
    if (shown > 1) lastStepRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [shown]);

  useEffect(() => {
    listDocumentSamples()
      .then((res) => {
        if (res.data?.length) {
          setSamples(res.data);
          return;
        }
        const status = res.response?.status;
        setError(
          status === 404
            ? "後端沒有範例文件的 API（404）：後端可能還在跑舊的程式，請重啟後端（停掉 make up 再重跑）"
            : `讀不到範例文件（${status ? `HTTP ${status}` : "後端沒有回應"}），請確認後端有開：docker compose logs --tail=50 backend`,
        );
      })
      .catch(() =>
        setError("連不到後端，請確認 make up 有在跑：docker compose logs --tail=50 backend"),
      );
  }, []);

  function updateFiled(next: Filed[]) {
    filedRef.current = next;
    setFiled(next);
  }

  async function recognize(file: File, label: string, from?: string) {
    const id = nextId.current++;
    const url = URL.createObjectURL(file);
    urls.current.push(url);
    const upload: Upload = {
      id,
      label,
      preview: {
        url,
        isPdf: file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf"),
      },
      result: null,
      error: null,
      from,
    };
    setUploads((current) => [upload, ...current]);
    setCurrentId(id);
    setShown(0);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("has_grant", String(hasGrant));
      form.append("apply_draft_rules", String(draftRules));
      for (const kind of new Set(filedRef.current.map((f) => f.kind)))
        form.append("previous", kind);
      const response = await fetch("/api/v1/dev/document-walkthrough", {
        method: "POST",
        body: form,
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(detailOf(body, response.status));
      const walked = body as WalkthroughOut;
      upload.result = walked;
      const { todo_title: todo, document_kind: kind, saved_path: saved } = walked;
      if (walked.status === "recognized" && todo && kind && saved) {
        updateFiled([...filedRef.current, { id, todo, kind, file: baseName(saved) }]);
        setDone((current) => ({ ...current, [todo]: walked.todo_complete }));
      }
      setShown(1);
    } catch (e) {
      upload.error = e instanceof Error ? e.message : String(e);
    }
    setUploads((current) => current.map((u) => (u.id === id ? { ...upload } : u)));
  }

  async function run(job: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await job();
    } finally {
      setBusy(false);
    }
  }

  function pickSample(sample: DocumentSampleOut) {
    void run(async () => {
      const response = await fetch(`/api/v1/dev/document-samples/${sample.name}`);
      if (!response.ok) {
        setError(`範例下載失敗（HTTP ${response.status}）`);
        return;
      }
      const blob = await response.blob();
      // 照片版範例是 JPG，其他是 PDF
      const ext = blob.type === "image/jpeg" ? "jpg" : "pdf";
      await recognize(
        new File([blob], `${sample.name}.${ext}`, { type: blob.type || "application/pdf" }),
        `範例：${sample.label}`,
      );
    });
  }

  function recognizeFiles(files: File[], from?: string) {
    // 一份一份辨識，後一份才看得到前一份已經通過
    void run(async () => {
      for (const file of files) await recognize(file, file.name, from);
    });
  }

  function pickFiles(e: ChangeEvent<HTMLInputElement>) {
    const files = [...(e.currentTarget.files ?? [])];
    e.currentTarget.value = "";
    recognizeFiles(files, uploadFrom.current);
    uploadFrom.current = undefined;
  }

  /** 打開選檔視窗；從待辦按的會記下是哪一項。 */
  function openPicker(from?: string) {
    uploadFrom.current = from;
    pickerRef.current?.click();
  }

  function removeFile(target: Filed) {
    const next = filedRef.current.filter((f) => f.id !== target.id);
    updateFiled(next);
    const kinds = next.filter((f) => f.todo === target.todo).map((f) => f.kind);
    setDone((current) => ({ ...current, [target.todo]: isComplete(target.todo, kinds) }));
  }

  function reset() {
    updateFiled([]);
    setDone({});
    setUploads([]);
    setCurrentId(null);
    setError(null);
  }

  const openCount = ALL_TODOS.filter((t) => !done[t.title]).length;
  const uploadOf = (id: number) => uploads.find((u) => u.id === id) ?? null;
  const current = uploads.find((u) => u.id === currentId) ?? null;
  const result = current?.result ?? null;
  const steps = result?.steps ?? [];
  const allShown = result !== null && shown >= steps.length;

  return (
    <section className="space-y-4" data-testid="document-walkthrough">
      <div className="space-y-1">
        <h2 className="text-xl font-semibold">上傳理賠文件（6 號文件辨識）</h2>
        <p className="text-sm text-gray-600">
          版面照規格書原型 2-3 行程頁與 2-4 上傳理賠文件。每份文件都用 6
          號真正的程式辨識，最下面可以一步一步看；Google Drive
          是假的，檔案不會存到任何地方；畫面上的文字都已經遮過個資。
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-md bg-gray-100 px-3 py-2">
        <span className="font-semibold">{TRIP_LINE.split(" · ")[0]}</span>
        <span className="text-sm text-gray-600">{TRIP_LINE.split(" · ")[1]}</span>
        <span className="text-sm text-gray-600">
          待辦 {ALL_TODOS.length - openCount}／{ALL_TODOS.length}
        </span>
      </div>

      {error && (
        <p role="alert" className="rounded-md bg-red-50 p-2 text-red-800" data-testid="error">
          {error}
        </p>
      )}

      <div className={box} data-testid="todos">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="font-semibold">
            待辦 <span className="text-sm font-normal text-gray-500">還缺 {openCount} 份</span>
          </h3>
          <Button
            type="button"
            className={secondary}
            disabled={busy || (!uploads.length && !filed.length)}
            onClick={reset}
          >
            清空重來
          </Button>
        </div>
        <div data-testid="passed">
          {PHASES.map((phase) => (
            <div key={phase.label} className="mt-2">
              <h4 className="font-semibold">
                {phase.label}{" "}
                <span className="text-sm font-normal text-gray-500">
                  {phase.groups.flatMap((g) => g.todos).filter((t) => done[t.title]).length}／
                  {phase.groups.flatMap((g) => g.todos).length}
                </span>
              </h4>
              {phase.groups.map((group) => (
                <div key={group.label}>
                  <p className="mt-1 border-b pb-0.5 text-sm text-gray-500">{group.label}</p>
                  {group.todos.map((todo) => {
                    const files = filed.filter((f) => f.todo === todo.title);
                    const lack = lackOf(
                      todo.title,
                      files.map((f) => f.kind),
                    );
                    const checked = !!done[todo.title];
                    return (
                      <div
                        key={todo.title}
                        className="grid grid-cols-[auto_1fr] gap-x-2 gap-y-1 border-b py-2"
                        data-testid={`todo-${todo.title}`}
                      >
                        <input
                          type="checkbox"
                          checked={checked}
                          readOnly
                          disabled
                          aria-label={`完成 ${todo.title}`}
                          className="mt-1 h-4 w-4 accent-green-600"
                        />
                        <span className={checked ? "text-gray-500 line-through" : ""}>
                          {todo.title}
                        </span>
                        <div className="col-start-2 flex flex-col gap-1 text-xs text-gray-500">
                          {files.map((f) => (
                            <span key={f.id} className="flex flex-wrap items-center gap-2">
                              <ZoomButton upload={uploadOf(f.id)} onZoom={setZoom} />
                              <span className="text-sm text-green-700">📎 {f.file}</span>
                              <span>（{f.kind}）</span>
                              <button
                                type="button"
                                className="text-red-600 hover:underline disabled:opacity-50"
                                disabled={busy}
                                onClick={() => removeFile(f)}
                                aria-label={`刪除 ${f.file}`}
                              >
                                刪除
                              </button>
                            </span>
                          ))}
                          {lack && (
                            <span
                              className="self-start rounded-md border border-dashed border-amber-400 bg-amber-50 px-2 py-1 text-amber-800"
                              data-testid="lack"
                            >
                              {lack}
                            </span>
                          )}
                          <Button
                            type="button"
                            className={`${small} self-start bg-white`}
                            disabled={busy}
                            onClick={() => openPicker(todo.title)}
                            data-testid="todo-upload"
                          >
                            上傳
                          </Button>
                          {todo.note && <span>注意：{todo.note}</span>}
                        </div>
                      </div>
                    );
                  })}
                </div>
              ))}
            </div>
          ))}
        </div>
        <p className="text-xs text-gray-500">
          勾選由 6
          號依文件自動完成；刪除檔案後依完成條件重算（機票＋登機證兩份都要，或一份搭機證明）。
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3 rounded-md border bg-white px-3 py-2">
        <span className="font-semibold">送件</span>
        <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">未送件</span>
        <span className="text-sm">
          {openCount ? `還缺 ${openCount} 份文件` : "文件已備齊（送件由 7 號負責，這裡不做）"}
        </span>
        <span className="flex-1" />
        <Button
          type="button"
          className={secondary}
          onClick={() => dropRef.current?.scrollIntoView({ behavior: "smooth", block: "center" })}
        >
          上傳文件
        </Button>
      </div>

      <section
        ref={dropRef}
        className={`space-y-3 rounded-lg border-2 border-dashed p-4 ${dragging ? "border-blue-600 bg-blue-100" : "border-blue-400 bg-blue-50"}`}
        data-testid="dropzone"
        aria-label="上傳理賠文件（可以把檔案拖進來）"
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          recognizeFiles([...e.dataTransfer.files]);
        }}
      >
        <h3 className="font-semibold">上傳理賠文件</h3>
        <div className="flex flex-col items-center gap-2 rounded-md bg-white/70 py-5 text-center">
          <Button
            type="button"
            className="rounded-md bg-blue-700 px-5 py-2 text-lg font-semibold text-white hover:bg-blue-800 disabled:opacity-50"
            disabled={busy}
            onClick={() => openPicker()}
            data-testid="pick"
          >
            ＋ 選擇檔案上傳
          </Button>
          <p className="text-sm text-gray-700">或把檔案拖到這個藍色框裡；可以一次選好幾份</p>
          <p className="text-sm font-semibold text-red-700">
            範例文件在桌面「團隊專題／6號範例文件」資料夾（01～07）
          </p>
        </div>
        <input
          ref={pickerRef}
          type="file"
          multiple
          hidden
          accept=".pdf,.jpg,.jpeg,.png"
          aria-label="上傳自己的文件"
          data-testid="file"
          onChange={pickFiles}
        />
        <p className="text-xs text-gray-600">
          PDF、JPG、PNG，每份 10 MB 內。上傳後依「事故類型_待辦名稱_序號」重新命名，存在 Google
          Drive（這裡是假的）。照片要在 .env 設定 Azure 才讀得到；沒設定時會停在第一步。
        </p>
        <div className="flex flex-wrap items-center gap-2" data-testid="samples">
          <span className="text-sm text-gray-600">或直接按範例（跟資料夾裡的檔案一樣）：</span>
          {samples.map((s) => (
            <Button
              key={s.name}
              type="button"
              disabled={busy}
              className={`${secondary} bg-white`}
              onClick={() => pickSample(s)}
            >
              {s.label}
            </Button>
          ))}
        </div>
        <div className="flex flex-wrap gap-4 text-sm">
          <label className="flex items-center gap-1">
            <input
              type="checkbox"
              checked={hasGrant}
              onChange={(e) => setHasGrant(e.target.checked)}
            />
            使用者已授權 Google Drive
          </label>
          <label className="flex items-center gap-1">
            <input
              type="checkbox"
              checked={draftRules}
              onChange={(e) => setDraftRules(e.target.checked)}
            />
            套用合格規範草稿（假設已確認）
          </label>
        </div>
      </section>

      {uploads.length > 0 && (
        <div className={box} data-testid="results">
          <h3 className="font-semibold">
            辨識結果 <span className="text-sm font-normal text-gray-500">Agent 6</span>
          </h3>
          {uploads.map((u) => (
            <ResultRow
              key={u.id}
              upload={u}
              onZoom={setZoom}
              selected={u.id === currentId}
              onSelect={() => {
                setCurrentId(u.id);
                setShown(u.result ? 1 : 0);
              }}
            />
          ))}
        </div>
      )}

      {current && (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
          <div className={box} data-testid="preview">
            <div className="flex items-center justify-between gap-2">
              <h3 className="font-semibold">你傳的文件：{current.label}</h3>
              <Button type="button" className={small} onClick={() => setZoom(current)}>
                ＋ 放大
              </Button>
            </div>
            {current.preview.isPdf ? (
              <iframe
                src={`${current.preview.url}#toolbar=0&view=FitH`}
                title={`文件預覽：${current.label}`}
                className="h-[560px] w-full rounded border"
              />
            ) : (
              <img
                src={current.preview.url}
                alt={`文件預覽：${current.label}`}
                className="max-h-[560px] w-full rounded border object-contain"
              />
            )}
            <p className="text-xs text-gray-500">
              預覽只在你的瀏覽器顯示；右邊的步驟裡，送出去的文字都已經遮過個資。
            </p>
          </div>
          {result && (
            <div className={box} data-testid="steps">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="font-semibold">6 號怎麼辨識的：一步一步看</h3>
                <div className="flex gap-2">
                  <Button
                    type="button"
                    className={primary}
                    disabled={allShown}
                    onClick={() => setShown((n) => n + 1)}
                    data-testid="next"
                  >
                    下一步（{Math.min(shown, steps.length)}／{steps.length}）
                  </Button>
                  <Button
                    type="button"
                    className={secondary}
                    disabled={allShown}
                    onClick={() => setShown(steps.length)}
                  >
                    全部顯示
                  </Button>
                </div>
              </div>
              <ol className="space-y-2">
                {steps.slice(0, shown).map((step, i) => {
                  const style = STATE_STYLE[step.state];
                  const info = STEP_INFO[step.key];
                  const isLast = i === shown - 1;
                  const nextStep = steps[shown];
                  return (
                    <li
                      key={step.key}
                      ref={isLast ? lastStepRef : undefined}
                      className={`rounded-md border p-2 ${style.className}`}
                      data-testid={`step-${step.key}`}
                    >
                      <div className="flex flex-wrap items-baseline justify-between gap-2">
                        <span className="font-semibold">
                          {i + 1}. {step.title}
                        </span>
                        <span className="text-xs">
                          {style.label}
                          {step.elapsed_ms != null && ` · ${step.elapsed_ms} ms`}
                        </span>
                      </div>
                      <p
                        className={`text-sm ${step.state === "skip" ? "" : "font-bold text-red-700"}`}
                      >
                        {step.state === "skip" ? step.summary : `重點：${step.summary}`}
                      </p>
                      {(step.inputs?.length ?? 0) + (step.outputs?.length ?? 0) > 0 && (
                        <div className="mt-2 grid gap-2 2xl:grid-cols-2">
                          <FieldList title="這次收到（輸入）" fields={step.inputs ?? []} />
                          <FieldList
                            title="這次產出（輸出）"
                            fields={step.outputs ?? []}
                            testId={`out-${step.key}`}
                          />
                        </div>
                      )}
                      {step.detail && (
                        <details className="mt-2" open={step.key === "privacy"}>
                          <summary className="cursor-pointer text-xs">
                            遮過個資的全文（{step.detail.split("\n").length} 行）
                          </summary>
                          <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap rounded bg-white/70 p-2 text-xs">
                            {highlight(step.detail)}
                          </pre>
                        </details>
                      )}
                      {info && <StepInfo info={info} />}
                      {isLast && nextStep && (
                        <div className="mt-2 flex justify-end">
                          <Button
                            type="button"
                            className={primary}
                            onClick={() => setShown((n) => n + 1)}
                            data-testid="next-bottom"
                          >
                            下一步：{nextStep.title} →（{shown}／{steps.length}）
                          </Button>
                        </div>
                      )}
                    </li>
                  );
                })}
              </ol>
              {allShown && (
                <div
                  className={`space-y-1 rounded-md border-2 p-3 ${RESULT_STYLE[result.status]}`}
                  data-testid="result"
                >
                  <p className="text-lg font-bold">結果：{result.status_label}</p>
                  <dl className="grid grid-cols-[7em_1fr] gap-x-2 gap-y-1 text-sm">
                    <dt className="text-gray-600">文件種類</dt>
                    <dd>{result.document_kind ?? "未判定"}</dd>
                    <dt className="text-gray-600">對到的待辦</dt>
                    <dd>{result.todo_title ?? "—"}</dd>
                    <dt className="text-gray-600">待辦</dt>
                    <dd>{result.todo_complete ? "已自動勾起來" : "沒有勾"}</dd>
                    <dt className="text-gray-600">給使用者的提醒</dt>
                    <dd>{result.reason ?? "—"}</dd>
                    <dt className="text-gray-600">存檔位置</dt>
                    <dd className="break-all">{result.saved_path ?? "沒有存檔"}</dd>
                  </dl>
                </div>
              )}
            </div>
          )}
        </div>
      )}
      {zoom && <ZoomView upload={zoom} onClose={() => setZoom(null)} />}
    </section>
  );
}

/** 文件旁邊的「＋」：點了放大看。 */
function ZoomButton({ upload, onZoom }: { upload: Upload | null; onZoom: (u: Upload) => void }) {
  if (!upload) return null;
  return (
    <button
      type="button"
      className="inline-flex h-5 w-5 items-center justify-center rounded border border-gray-400 bg-white text-sm font-bold leading-none text-gray-700 hover:bg-gray-100"
      onClick={() => onZoom(upload)}
      aria-label={`放大 ${upload.label}`}
      title="放大看這份文件"
    >
      ＋
    </button>
  );
}

/** 全螢幕看一份文件；按背景、「關閉」或 Esc 關掉。 */
function ZoomView({ upload, onClose }: { upload: Upload; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-label={`放大：${upload.label}`}
      data-testid="zoom"
    >
      <button
        type="button"
        className="absolute inset-0 bg-black/60"
        aria-label="關閉放大"
        onClick={onClose}
      />
      <div className="relative flex h-full w-full max-w-5xl flex-col gap-2 rounded-lg bg-white p-3">
        <div className="flex items-center justify-between gap-2">
          <h3 className="font-semibold">{upload.label}</h3>
          <Button type="button" className={secondary} onClick={onClose}>
            ✕ 關閉
          </Button>
        </div>
        {upload.preview.isPdf ? (
          <iframe
            src={`${upload.preview.url}#view=FitH`}
            title={`放大：${upload.label}`}
            className="w-full flex-1 rounded border"
          />
        ) : (
          <img
            src={upload.preview.url}
            alt={`放大：${upload.label}`}
            className="min-h-0 w-full flex-1 rounded border object-contain"
          />
        )}
      </div>
    </div>
  );
}

const link = "text-blue-700 underline hover:text-blue-900";

/** 後端回傳的「這次」輸入或輸出；ok 是 true／false 時加上 ✓／✗。 */
function FieldList({
  title,
  fields,
  testId,
}: {
  title: string;
  fields: StepField[];
  testId?: string;
}) {
  return (
    <div className="rounded bg-white/80 p-2 text-xs text-gray-800" data-testid={testId}>
      <p className="mb-1 font-semibold">{title}</p>
      {fields.length ? (
        <dl className="space-y-1">
          {fields.map((f) => (
            <div key={`${f.label}-${f.value}`}>
              <dt className="text-gray-500">
                {f.ok != null && (
                  <span className={`mr-1 ${f.ok ? "text-green-700" : "text-red-700"}`}>
                    {f.ok ? "✓" : "✗"}
                  </span>
                )}
                {f.label}
              </dt>
              <dd
                className={`break-words pl-3 font-mono ${f.ok != null ? "font-bold text-red-700" : ""}`}
              >
                {f.value}
              </dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="text-gray-500">—</p>
      )}
    </div>
  );
}

/** 遮過的地方（〔姓名〕這類代號）標上底色，看得出換掉了哪裡。 */
function highlight(text: string): ReactNode[] {
  return text.split(/(〔[^〕]{1,8}〕)/).map((part, i) =>
    /^〔[^〕]{1,8}〕$/.test(part) ? (
      // biome-ignore lint/suspicious/noArrayIndexKey: 同一段文字切出來的片段，順序固定
      <mark key={i} className="rounded bg-yellow-200 px-0.5">
        {part}
      </mark>
    ) : (
      part
    ),
  );
}

/** 一個步驟的技術、程式位置、ticket（固定說明）。 */
function StepInfo({ info }: { info: StepInfoData }) {
  return (
    <dl
      className="mt-2 grid grid-cols-[4.5em_1fr] gap-x-2 gap-y-1 rounded bg-white/70 p-2 text-xs text-gray-700"
      data-testid="step-info"
    >
      <dt className="font-semibold">技術</dt>
      <dd>{info.tech}</dd>
      <dt className="font-semibold">後端</dt>
      <dd className="flex flex-col">
        {info.code.map((c) => (
          <span key={c.file}>
            <a
              className={`${link} font-mono`}
              href={`${CODE}/${c.file}`}
              target="_blank"
              rel="noreferrer"
            >
              {`backend/app/${c.file.startsWith("../../") ? c.file.slice(6) : `agents/document/${c.file}`}`}
            </a>
            ：{c.fn}
          </span>
        ))}
      </dd>
      <dt className="font-semibold">Ticket</dt>
      <dd className="flex flex-wrap gap-x-2">
        {info.tickets.map((n) => (
          <a key={n} className={link} href={issue(n)} target="_blank" rel="noreferrer">
            #{n}
          </a>
        ))}
        {info.docs?.map((d) => (
          <a key={d.label} className={link} href={d.href} target="_blank" rel="noreferrer">
            {d.label}
          </a>
        ))}
      </dd>
    </dl>
  );
}

/** 辨識結果的一行，文字照原型 2-4c：✓ 通過／✗ 不合格或不通過／? 無法辨識。 */
function ResultRow({
  upload,
  selected,
  onSelect,
  onZoom,
}: {
  upload: Upload;
  selected: boolean;
  onSelect: () => void;
  onZoom: (u: Upload) => void;
}) {
  const r = upload.result;
  let line: ReactNode;
  if (upload.error) {
    line = <span className="text-red-700">✗ 辨識失敗：{upload.error}</span>;
  } else if (!r) {
    line = <span className="text-gray-500">辨識中…</span>;
  } else if (r.status === "recognized" && r.todo_title) {
    line = (
      <>
        <span className="text-green-700">
          ✓ 通過：{groupOf(r.todo_title)}｜{r.todo_title}
        </span>
        {r.saved_path && (
          <span className="block text-green-700">存為 {baseName(r.saved_path)}</span>
        )}
        {r.reason && <span className="block text-amber-700">{r.reason}</span>}
        {upload.from && upload.from !== r.todo_title && (
          <span className="block text-red-700">
            你從「{upload.from}」上傳，6 號認出這份屬於「{r.todo_title}」，已放到那一項
          </span>
        )}
      </>
    );
  } else if (r.status === "needs_review") {
    line = <span className="text-amber-700">? {r.reason ?? "無法辨識，請選擇對應的待辦"}</span>;
  } else {
    line = (
      <span className="text-red-700">
        ✗ {r.reason ?? "不是需要的文件，請重新上傳"}（檔案未保留）
      </span>
    );
  }
  return (
    <div
      className={`grid grid-cols-[1fr_auto] items-center gap-x-3 border-b py-2 text-sm ${selected ? "bg-gray-50" : ""}`}
      data-testid="result-row"
    >
      <span>
        <ZoomButton upload={upload} onZoom={onZoom} /> 📄 {upload.label}
        <br />
        {line}
      </span>
      <button type="button" className={small} disabled={selected || !r} onClick={onSelect}>
        {selected ? "下面正在看" : "看步驟"}
      </button>
    </div>
  );
}
