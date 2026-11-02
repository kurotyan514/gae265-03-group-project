import { useEffect, useRef, useState } from "react";
import type { IngestEventOut } from "../../client/types.gen";
import { STEPS } from "./steps";

type Outcome = "running" | "done" | "failed" | "review";
type StationState = "done" | "current" | "pending" | "failed" | "review";

/** 小人走一站的時間（毫秒），位移動畫與走路姿勢共用。 */
const MOVE_MS = 700;

const stationIndex = (step: string) => STEPS.findIndex((s) => s.key === step);

/** 事件序列走到第幾站；還沒有任何步驟的事件時是 -1。 */
function currentStation(events: IngestEventOut[]): number {
  return events.reduce((max, e) => Math.max(max, stationIndex(e.step)), -1);
}

/**
 * 結局只看已顯示的 `done` 事件：ok 是完成、warning 是等人工確認、error 是失敗或被拒絕。
 * 還沒演到 `done` 之前一律是進行中，不提前判斷。
 */
function outcomeOf(terminal: IngestEventOut | undefined): Outcome {
  if (!terminal) return "running";
  if (terminal.status === "ok") return "done";
  return terminal.status === "warning" ? "review" : "failed";
}

/** 像素小人拖著行李的 SVG（1 格 = 2px 的像素風）；腿用 CSS 逐格動畫交替，失敗時變灰並皺眉。 */
function Walker({ walking, failed }: { walking: boolean; failed: boolean }) {
  return (
    <svg
      viewBox="0 0 26 16"
      width="52"
      height="32"
      shapeRendering="crispEdges"
      aria-hidden
      className={[walking && "px-walking", failed && "px-failed"].filter(Boolean).join(" ")}
    >
      {/* 行李箱與牽繩 */}
      <rect x="0" y="8" width="4" height="1" className="px-bag-dark" />
      <rect x="0" y="9" width="8" height="6" className="px-bag" />
      <rect x="0" y="11" width="8" height="1" className="px-bag-dark" />
      <rect x="1" y="15" width="2" height="1" className="px-pants" />
      <rect x="5" y="15" width="2" height="1" className="px-pants" />
      <rect x="8" y="11" width="5" height="1" className="px-rope" />
      {/* 人：頭髮、臉、上衣、手 */}
      <rect x="13" y="0" width="5" height="2" className="px-hair" />
      <rect x="13" y="2" width="5" height="3" className="px-skin" />
      <rect x="17" y="3" width="1" height="1" className="px-hair" />
      {failed && <rect x="14" y="4" width="3" height="1" className="px-mouth" />}
      <rect x="12" y="5" width="6" height="5" className="px-shirt" />
      <rect x="11" y="6" width="2" height="5" className="px-shirt" />
      {/* 腿：兩隻交替抬起 */}
      <rect x="13" y="10" width="2" height="5" className="px-pants px-leg-a" />
      <rect x="16" y="10" width="2" height="5" className="px-pants px-leg-b" />
    </svg>
  );
}

/**
 * 示範模式用的進度軌道：7 個站點對應 7 個步驟，像素小人拖著行李走到目前進行中的那一站。
 * 位置與結局完全由已顯示的事件決定，不自行推測後端狀態。
 */
export function ProgressTrack({ events }: { events: IngestEventOut[] }) {
  const terminal = [...events].reverse().find((e) => e.step === "done");
  const outcome = outcomeOf(terminal);
  const current = outcome === "done" ? STEPS.length - 1 : currentStation(events);

  // 失敗或待確認時，小人停在「出問題的那一站」：終局之前最後一個步驟事件若是 error，就是它所屬的步驟
  // （更早的、後來已經恢復的錯誤不算）；終局錯誤沒有指定步驟時，就停在最後走到的那一站
  const lastStepEvent = [...events].reverse().find((e) => e.step !== "done");
  const errorEvent = lastStepEvent?.status === "error" ? lastStepEvent : undefined;
  const problem = errorEvent ? stationIndex(errorEvent.step) : -1;
  const stopped = outcome === "failed" || outcome === "review";
  const position = Math.max(stopped && problem >= 0 ? problem : current, 0);

  // 換站時走路，MOVE_MS 後站定。用計時器而不是 transitionend：沒有位移（分頁在背景、
  // 動畫被關掉）時 transitionend 不會來，腿就會一直動。
  // 比對「上一個位置」而不是「是否掛載過」，StrictMode 在開發時重跑 effect 也不會誤判。
  const [moving, setMoving] = useState(false);
  const lastPosition = useRef(position);
  useEffect(() => {
    if (lastPosition.current === position) return;
    lastPosition.current = position;
    setMoving(true);
    const timer = setTimeout(() => setMoving(false), MOVE_MS);
    return () => clearTimeout(timer);
  }, [position]);

  const embed = [...events].reverse().find((e) => e.step === "embed");
  const embedProgress =
    embed?.current != null && embed.total != null && embed.total > 0
      ? `${embed.current}/${embed.total}`
      : null;

  const stateOf = (i: number): StationState => {
    if (outcome === "done") return "done";
    if (stopped) return i < position ? "done" : i === position ? outcome : "pending";
    return i < current ? "done" : i === current ? "current" : "pending";
  };

  // 失敗顯示出問題的那一步的訊息（例如 LLM 判斷不是條款的理由）；待確認顯示終局訊息
  const outcomeMessage =
    outcome === "failed"
      ? (errorEvent?.message ?? terminal?.message)
      : outcome === "review"
        ? terminal?.message
        : undefined;
  const centerPercent = ((position + 0.5) / STEPS.length) * 100;

  return (
    <div className="overflow-x-auto" data-testid="track">
      <div className="relative min-w-[40rem] pt-10 pb-2">
        <div
          className="absolute top-0 transition-[left] ease-linear"
          style={{ left: `${centerPercent}%`, transitionDuration: `${MOVE_MS}ms` }}
          data-testid="walker"
          data-station={current < 0 ? "start" : STEPS[position]?.key}
          data-walking={moving}
          data-outcome={outcome}
        >
          <div className="-translate-x-1/2">
            <Walker walking={moving} failed={outcome === "failed"} />
          </div>
        </div>
        <ol
          className="relative grid"
          style={{ gridTemplateColumns: `repeat(${STEPS.length}, minmax(0, 1fr))` }}
          aria-label="agent 處理進度"
        >
          {STEPS.map((step, i) => (
            <li
              key={step.key}
              className="px-station relative flex flex-col items-center gap-1 text-center"
              data-testid={`station-${step.key}`}
              data-state={stateOf(i)}
            >
              <span aria-hidden className="px-dot" />
              {/* 每一段是 inline-block，只會在底線之後換行，不會從字中間切開；工具名稱是固定常數，段名不重複 */}
              <code className="px-1 text-xs">
                {step.tool.split(/(?<=_)/).map((part) => (
                  <span key={part} className="inline-block">
                    {part}
                  </span>
                ))}
              </code>
              {step.key === "embed" && embedProgress && (
                <span className="font-mono text-xs text-gray-600" data-testid="station-sub-embed">
                  {embedProgress}
                </span>
              )}
            </li>
          ))}
        </ol>
        {outcomeMessage && (
          <div
            className="relative mt-3"
            role="status"
            data-testid="track-outcome"
            data-outcome={outcome}
          >
            <span
              aria-hidden
              className={`absolute -top-1.5 -ml-1.5 size-3 rotate-45 border-t border-l ${
                outcome === "failed" ? "border-red-300 bg-red-50" : "border-amber-300 bg-amber-50"
              }`}
              style={{ left: `${centerPercent}%` }}
            />
            <p
              className={`rounded-lg border px-3 py-2 text-sm ${
                outcome === "failed"
                  ? "border-red-300 bg-red-50 text-red-900"
                  : "border-amber-300 bg-amber-50 text-amber-900"
              }`}
            >
              {outcome === "failed" ? "❌" : "⚠️"} {outcomeMessage}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
