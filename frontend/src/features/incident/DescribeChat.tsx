import type { ReactNode } from "react";
import { AskBar, ChatLog, ChatMessage } from "../../components/ui/Chat";
import { Chip, ChipGroup } from "../../components/ui/Chip";
import { box } from "./shared";

/** 2-2 的 AI 第一句（畫面上的開場白，不是 5 號的回覆，不存進對話紀錄）。 */
export const FIRST_QUESTION =
  "發生什麼事了？用一兩句話描述就好，例如：颱風來了，回台灣的班機被取消。";

export type ChatLine = {
  from: "me" | "ai";
  text: string;
  citations?: { insurance_code: string; article_no: number }[];
};

/**
 * 2-2 描述事故的對話卡（DESIGN.md 7.9）：對話區（最小高 320）、AI 追問的選項 Chip、提問列（500 字）。
 * 建立前（還沒有事件）與追問中共用。送出中時輸入框保留內容並停用，下方顯示「正在整理…」。
 */
export function DescribeChat({
  lines,
  quickReplies,
  placeholder,
  value,
  onChange,
  busy,
  onSend,
  maxLength = 500,
  minHeight = 320,
  tall = false,
  logFooter,
  busyOverlay,
}: {
  lines: ChatLine[];
  quickReplies: string[];
  placeholder: string;
  value: string;
  onChange: (value: string) => void;
  busy: boolean;
  onSend: (text: string, mode: "text" | "quick_reply") => void;
  /** 字數上限；描述事故 500，理賠頁的問答 300。 */
  maxLength?: number;
  /** 對話區最小高（px）。 */
  minHeight?: number;
  /** 桌機（lg 以上）固定高度、內部捲動，輸入列貼底（雙欄版型用）。 */
  tall?: boolean;
  /** 放在對話區最下方左側的東西（理賠頁的「＋ 有新狀況」）。 */
  logFooter?: ReactNode;
  /** 有值時，送出中改用全頁半透明遮罩＋轉圈顯示這段文字（2-2「正在整理理賠項目…」）。 */
  busyOverlay?: string;
}) {
  return (
    <section className={box} aria-label="對話">
      <ChatLog
        minHeight={minHeight}
        className={tall ? "lg:h-[calc(100vh-22rem)] lg:max-h-none lg:min-h-[420px]" : ""}
        data-testid="messages"
      >
        {lines.map((line, i) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: 訊息沒有穩定 id，順序固定
          <ChatMessage key={i} from={line.from}>
            {line.text}
            {line.citations && line.citations.length > 0 && (
              <span className="t-caption text-muted" data-testid="citations">
                依據：
                {line.citations.map((c) => `${c.insurance_code} 第 ${c.article_no} 條`).join("、")}
              </span>
            )}
          </ChatMessage>
        ))}
        {logFooter && (
          <li className="mt-auto list-none pt-2" data-testid="log-footer">
            {logFooter}
          </li>
        )}
      </ChatLog>
      {busy && busyOverlay && (
        <div
          role="status"
          className="fixed inset-0 z-50 flex flex-col items-center justify-center gap-4 bg-paper/80"
          data-testid="busy"
        >
          <span
            aria-hidden="true"
            className="size-10 animate-spin rounded-full border-4 border-line border-t-leaf"
          />
          <span className="t-label-lg text-heading">{busyOverlay}</span>
        </div>
      )}
      {busy && !busyOverlay && (
        <p role="status" className="m-0 t-caption text-muted" data-testid="busy">
          正在整理…
        </p>
      )}
      {quickReplies.length > 0 && (
        <ChipGroup data-testid="quick-replies">
          {quickReplies.map((q) => (
            <Chip key={q} disabled={busy} onClick={() => onSend(q, "quick_reply")}>
              {q}
            </Chip>
          ))}
        </ChipGroup>
      )}
      <AskBar
        value={value}
        onChange={onChange}
        onSubmit={() => onSend(value, "text")}
        maxLength={maxLength}
        placeholder={placeholder}
        disabled={busy}
        inputName="content"
        inputTestId="message"
        submitTestId="send"
      />
    </section>
  );
}
