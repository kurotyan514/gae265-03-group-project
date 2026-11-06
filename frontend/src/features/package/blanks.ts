// 7 號送件信裡的空格固定寫成「（請填寫＋項目）」。
// 這是 7 號與前端的約定，見 docs/specs/agent-7-package.md。
const BLANK = /（請填寫([^）]+)）/g;

export type LetterPart = { text: string; blank?: string };

/** 把信件文字切成一般文字與空格，畫面用來把空格標色。 */
export function splitBlanks(text: string): LetterPart[] {
  const parts: LetterPart[] = [];
  let last = 0;
  for (const match of text.matchAll(BLANK)) {
    const start = match.index ?? 0;
    if (start > last) parts.push({ text: text.slice(last, start) });
    parts.push({ text: match[0], blank: match[1] });
    last = start + match[0].length;
  }
  if (last < text.length) parts.push({ text: text.slice(last) });
  return parts;
}

/** 要填的項目，照出現的順序，重複的只列一次（例如保險期間在主旨與內文都有）。 */
export function missingItems(...texts: string[]): string[] {
  const items: string[] = [];
  for (const text of texts) {
    for (const [, item = ""] of text.matchAll(BLANK)) {
      if (!items.includes(item)) items.push(item);
    }
  }
  return items;
}
