import { useEffect, useRef, useState } from "react";
import type { IngestEventOut } from "../../client/types.gen";
import { dwellMs, GAP_MS } from "./steps";

function delayAfter(event: IngestEventOut | undefined, speed: number): number {
  if (!event) return 0;
  const base = event.status === "running" ? dwellMs(event.step) : GAP_MS;
  return base / speed;
}

/**
 * 示範模式用：把已經到齊的事件改成一筆一筆慢慢呈現。
 * 只改變「何時顯示」，不改資料；關閉時原樣回傳。
 * 同一步驟連續的進度事件（例如計算向量）只顯示最新一筆，避免排隊拖太久。
 */
export function usePacedEvents(
  incoming: IngestEventOut[],
  { enabled, speed }: { enabled: boolean; speed: number },
): IngestEventOut[] {
  const [revealedSeq, setRevealedSeq] = useState(0);

  // 開關切換時從頭演一遍。在渲染中重置，第一個示範畫面就不會用到舊的進度
  const [prevEnabled, setPrevEnabled] = useState(enabled);
  if (prevEnabled !== enabled) {
    setPrevEnabled(enabled);
    setRevealedSeq(0);
  }

  // 直播時事件會一直進來：計時器不能每次都重設，否則事件比停留時間更密就永遠演不出來。
  // 所以計時器的觸發時機只看「顯示到哪了」，事件內容則從 ref 讀最新的。
  const incomingRef = useRef(incoming);
  incomingRef.current = incoming;
  const hasPending = incoming.some((e) => e.seq > revealedSeq);

  useEffect(() => {
    if (!enabled || !hasPending) return;
    const last = incomingRef.current.find((e) => e.seq === revealedSeq);
    const timer = setTimeout(
      () => {
        const pending = incomingRef.current.filter((e) => e.seq > revealedSeq);
        // 前一筆也是某步驟的進度時，跳到這一串同步驟連續進度的最後一筆
        const sameProgress = (e: IngestEventOut | undefined) =>
          e?.status === "running" && e.step === last?.step;
        let i = 0;
        if (last?.status === "running") {
          while (sameProgress(pending[i]) && sameProgress(pending[i + 1])) i++;
        }
        const next = pending[i];
        if (next) setRevealedSeq(next.seq);
      },
      delayAfter(last, speed),
    );
    return () => clearTimeout(timer);
  }, [enabled, speed, hasPending, revealedSeq]);

  return enabled ? incoming.filter((e) => e.seq <= revealedSeq) : incoming;
}
