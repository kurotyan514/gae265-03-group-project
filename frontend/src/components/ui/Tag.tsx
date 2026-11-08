import type { ReactNode } from "react";

/**
 * 標籤類（DESIGN.md 6.14）。狀態用「顏色點」，不用色塊：綠點＝可能適用／完成，
 * 珊瑚點＝不在範圍／需處理，黃點＝待確認。
 */
const pill =
  "inline-flex items-center gap-1.5 rounded-chip border border-line bg-white px-3 py-0.5 t-caption-bold text-ink";

const dot = (color: string) => (
  <span aria-hidden="true" className={`size-2 flex-none rounded-full ${color}`} />
);

export type PillTone = "plain" | "need" | "sent" | "closed";

/** Pill：預設白底框；need 前有珊瑚點、sent 前有綠點、closed 品牌色框與字。 */
export function Pill({ tone = "plain", children }: { tone?: PillTone; children: ReactNode }) {
  const closed = tone === "closed" ? "border-brand text-brand" : "";
  return (
    <span className={`${pill} ${closed}`}>
      {tone === "need" && dot("bg-coral")}
      {tone === "sent" && dot("bg-leaf")}
      {children}
    </span>
  );
}

/** 進度 Pill：例如「待辦 2／5」。 */
export function ProgressPill({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex rounded-chip bg-leaf-soft px-3 py-0.5 t-label text-heading">
      {children}
    </span>
  );
}

export type Conclusion = "applicable" | "excluded" | "insufficient";

/** 結論 Pill：可能適用（綠點）／依條款不在保障範圍（珊瑚點）／資訊不足（黃點）。 */
export function ConclusionPill({
  conclusion,
  children,
}: {
  conclusion: Conclusion;
  children: ReactNode;
}) {
  const style =
    conclusion === "applicable"
      ? "bg-leaf-soft text-brand"
      : "border border-line bg-white text-ink";
  const color =
    conclusion === "applicable" ? "bg-leaf" : conclusion === "excluded" ? "bg-coral" : "bg-sun";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-chip px-3 py-0.5 t-caption-bold ${style}`}
    >
      {dot(color)}
      {children}
    </span>
  );
}

/** 事實 Pill：事故卡裡「你提供的前提」，例如「發生日期：2026/07/09」。 */
export function FactPill({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex rounded-chip border border-line bg-paper px-3 py-0.5 t-caption text-ink">
      {children}
    </span>
  );
}

export type TagTone = "plain" | "new" | "missing";

/** 待辦上的小 Tag：新增（品牌色底）、未附文件（珊瑚框）、不適用等（灰框）。 */
export function TodoTag({ tone = "plain", children }: { tone?: TagTone; children: ReactNode }) {
  const style =
    tone === "new"
      ? "border-brand bg-brand text-white"
      : tone === "missing"
        ? "border-coral text-danger"
        : "border-line text-muted";
  return (
    <span className={`ml-2 inline-flex rounded-tag border px-2 py-px align-[3px] t-micro ${style}`}>
      {children}
    </span>
  );
}
