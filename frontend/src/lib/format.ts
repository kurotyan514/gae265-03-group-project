/** 保額顯示成「萬」：1_000_000 → "100 萬"。 */
export const wan = (n: number) => `${(n / 10_000).toLocaleString("zh-TW")} 萬`;
