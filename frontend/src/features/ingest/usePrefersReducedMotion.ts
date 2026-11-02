import { useSyncExternalStore } from "react";

const QUERY = "(prefers-reduced-motion: reduce)";

// 整個頁面共用同一個 MediaQueryList；舊瀏覽器或沒有 matchMedia 的環境就當作沒有這個偏好
let media: MediaQueryList | null | undefined;
function getMedia(): MediaQueryList | null {
  if (media === undefined) {
    media = typeof window !== "undefined" && window.matchMedia ? window.matchMedia(QUERY) : null;
  }
  return media;
}

function subscribe(onChange: () => void) {
  const list = getMedia();
  list?.addEventListener?.("change", onChange);
  return () => list?.removeEventListener?.("change", onChange);
}

/** 系統是否設為「減少動態」；使用者中途改設定也會跟著更新。 */
export function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => getMedia()?.matches ?? false,
    () => false,
  );
}
