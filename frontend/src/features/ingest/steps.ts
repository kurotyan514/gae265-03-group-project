/** 條款上傳 agent 的 7 個步驟。`tool` 是後端該步驟實際呼叫的函式，要與 backend/app/ingest 保持一致。 */
export const STEPS = [
  { key: "extract", label: "讀取 PDF", tool: "extract_pages", kind: "program" },
  { key: "classify", label: "判斷是否為保險條款", tool: "llm_classify", kind: "llm" },
  { key: "chunk", label: "切 chunk（一條一段）", tool: "split_into_chunks", kind: "program" },
  { key: "repair", label: "自動修復", tool: "repair_articles", kind: "program" },
  { key: "validate", label: "驗證條文", tool: "validate_articles", kind: "program" },
  { key: "embed", label: "計算 embedding", tool: "aembed_documents", kind: "program" },
  { key: "import", label: "寫入資料庫", tool: "import_catalog", kind: "program" },
] as const;

export type Step = (typeof STEPS)[number];

export const KIND_LABEL: Record<Step["kind"], string> = {
  program: "程式工具",
  llm: "LLM 判斷",
};

const DEFAULT_DWELL_MS = 1500;
const DWELL_MS: Record<string, number> = { classify: 2500 };

/** 示範模式下，步驟「進行中」至少停留的毫秒數（倍速 1 時）。LLM 那步較久，讓觀眾看清楚。 */
export const dwellMs = (step: string): number => DWELL_MS[step] ?? DEFAULT_DWELL_MS;

/** 一個步驟完成後，到下一個步驟開始之間的間隔（倍速 1 時）。 */
export const GAP_MS = 400;
