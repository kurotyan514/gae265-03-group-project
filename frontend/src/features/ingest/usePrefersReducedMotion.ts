import { useSyncExternalStore } from "react";

const QUERY = "(prefers-reduced-motion: reduce)";

// 沒有 matchMedia 的環境就當作沒有這個偏好。每次都重新取得，不快取：測試切換偏好時才讀得到新的
function getMedia(): MediaQueryList | null {
  return typeof window !== "undefined" && window.matchMedia ? window.matchMedia(QUERY) : null;
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
