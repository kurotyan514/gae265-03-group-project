/**
 * 合訂本確認畫面：把「不收」的區段勾成「收錄」時，帶入下一個可用的險種代碼。
 * 設定檔裡不收的區段代碼是 `skip_<公司>_<名稱>`（例如 skip_huanan_phone），不能直接拿來收錄。
 */
const SKIPPED = /^skip_([a-z0-9]+)/i;
const NUMBERED = /^([A-Za-z]+)(\d+)$/;

/** 區段代碼是不收的區段用的 `skip_` 開頭。 */
export function isSkipCode(code: string): boolean {
  return code.trim().toLowerCase().startsWith("skip_");
}

/**
 * 下一個可用的代碼：公司代號取自 skip_ 代碼的第二段（skip_huanan_phone → HUANAN），
 * 流水號是這份清單與資料庫已有的同公司代碼的最大號碼加一（HUANAN08 之後是 HUANAN09）。
 * 公司代號取不到就回 null，由使用者自己填。
 */
export function nextInsuranceCode(
  skipCode: string,
  sections: { code?: string }[],
  taken: string[],
): string | null {
  const prefix = SKIPPED.exec(skipCode.trim())?.[1]?.toUpperCase();
  if (!prefix) return null;
  let max = 0;
  for (const code of [...sections.map((s) => s.code ?? ""), ...taken]) {
    const m = NUMBERED.exec(code.trim());
    if (m?.[1]?.toUpperCase() === prefix) max = Math.max(max, Number(m[2]));
  }
  return `${prefix}${String(max + 1).padStart(2, "0")}`;
}
