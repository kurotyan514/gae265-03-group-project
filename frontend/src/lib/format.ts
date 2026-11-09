/** 保額顯示成「萬」：1_000_000 → "100 萬"。 */
export const wan = (n: number) => `${(n / 10_000).toLocaleString("zh-TW")} 萬`;

/** 金額：985 → "985 元"。 */
export const money = (n: number) => `${n.toLocaleString("zh-TW")} 元`;

/** ISO 時間顯示成台北時間的日期：2026-11-07T20:00:00Z → "2026/11/08"。 */
export const taipeiDate = (iso: string) =>
  new Date(iso).toLocaleDateString("zh-TW", {
    timeZone: "Asia/Taipei",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
