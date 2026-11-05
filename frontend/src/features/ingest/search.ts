export type IngestSearch = { demo?: 1; speed?: number };

/** 條款上傳頁的網址參數：?demo=1 開啟示範模式；?speed=2 調整示範的播放倍速（預設 1，上限 100）。 */
export function validateIngestSearch(search: Record<string, unknown>): IngestSearch {
  return {
    demo: search.demo === 1 || search.demo === "1" || search.demo === true ? 1 : undefined,
    speed:
      typeof search.speed === "number" && search.speed > 0
        ? Math.min(search.speed, 100)
        : undefined,
  };
}
