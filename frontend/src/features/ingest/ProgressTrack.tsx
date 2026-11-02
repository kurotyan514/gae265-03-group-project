import { useEffect, useRef, useState } from "react";
import type { IngestEventOut } from "../../client/types.gen";
import { STEPS } from "./steps";

type StationState = "done" | "current" | "pending";

/** 小人走一站的時間（毫秒），位移動畫與走路姿勢共用。 */
const MOVE_MS = 700;

/** 事件序列走到第幾站；還沒有任何步驟的事件時是 -1。 */
function currentStation(events: IngestEventOut[]): number {
  return events.reduce(
    (max, e) =>
      Math.max(
        max,
        STEPS.findIndex((s) => s.key === e.step),
      ),
    -1,
  );
}

/** 像素小人拖著行李的 SVG（1 格 = 2px 的像素風）；腿用 CSS 逐格動畫交替。 */
function Walker({ walking }: { walking: boolean }) {
  return (
    <svg
      viewBox="0 0 26 16"
      width="52"
      height="32"
      shapeRendering="crispEdges"
      aria-hidden
      className={walking ? "px-walking" : undefined}
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
 * 位置完全由已顯示的事件決定，不自行推測後端狀態。
 */
export function ProgressTrack({ events }: { events: IngestEventOut[] }) {
  const finished = events.some((e) => e.step === "done" && e.status === "ok");
  const current = finished ? STEPS.length - 1 : currentStation(events);
  const position = Math.max(current, 0);

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

  const stateOf = (i: number): StationState =>
    finished || i < current ? "done" : i === current ? "current" : "pending";

  return (
    <div className="overflow-x-auto" data-testid="track">
      <div className="relative min-w-[40rem] pt-10 pb-2">
        <div
          className="absolute top-0 transition-[left] ease-linear"
          style={{
            left: `${((position + 0.5) / STEPS.length) * 100}%`,
            transitionDuration: `${MOVE_MS}ms`,
          }}
          data-testid="walker"
          data-station={current < 0 ? "start" : STEPS[position]?.key}
          data-walking={moving}
        >
          <div className="-translate-x-1/2">
            <Walker walking={moving} />
          </div>
        </div>
        <ol
          className="relative grid"
          style={{ gridTemplateColumns: `repeat(${STEPS.length}, minmax(0, 1fr))` }}
          aria-label="agent 處理進度"
        >
          {STEPS.map((step, i) => {
            const state = stateOf(i);
            return (
              <li
                key={step.key}
                className="px-station relative flex flex-col items-center gap-1 text-center"
                data-testid={`station-${step.key}`}
                data-state={state}
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
            );
          })}
        </ol>
      </div>
    </div>
  );
}
