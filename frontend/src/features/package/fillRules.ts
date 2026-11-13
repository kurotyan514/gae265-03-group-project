// 送件信空格的格式檢查：被保險人姓名與聯絡電話。
// 和後端 backend/app/domain/incident/fill_rules.py 同一套規則，送件 API 也會擋（422）。
// 只檢查有填的值；沒填的空格由「還有空格不能寄出」處理。

export const NAME_ITEM = "被保險人姓名";
export const PHONE_ITEM = "聯絡電話";

// 中文：基本區、擴充 A、相容字、擴充 B～H（罕用字）與「〇」
const HAN = "\\u3007\\u3400-\\u4dbf\\u4e00-\\u9fff\\uf900-\\ufaff\\u{20000}-\\u{3134f}";
const LETTER = `[${HAN}A-Za-z]`;
const NAME = new RegExp(`^${LETTER}(?:[${HAN}A-Za-z \\u00b7\\u2027\\-']*${LETTER})?$`, "u");

const MOBILE = /^09\d{8}$/;
// 市話：區碼 0 開頭 2～4 碼（不是 09），可以加括號；號碼中間最多一個連字號；可加分機
const LANDLINE =
  /^(?:\((0[2-8]\d{0,2})\)|(0[2-8]\d{0,2})-?)(\d{2,4}-?\d{3,4})(?:\s*(?:#|分機|ext\.?\s*)\d{1,6})?$/i;

export const NAME_PROBLEM =
  "被保險人姓名只能填中文或英文（可以有空格、·、-、'），開頭結尾要是文字，2～50 字";
export const PHONE_PROBLEM = "聯絡電話請填手機（09 開頭共 10 碼）或含區碼的市話";

export function nameOk(value: string): boolean {
  const length = [...value].length; // 罕用字是一個字，不是兩個 UTF-16 單位
  return length >= 2 && length <= 50 && NAME.test(value);
}

export function phoneOk(value: string): boolean {
  if (MOBILE.test(value)) return true;
  const match = LANDLINE.exec(value);
  if (!match) return false;
  const digits = (match[1] ?? match[2] ?? "") + (match[3] ?? "").replace("-", "");
  // 台灣市話含區碼共 9～10 碼
  return digits.length >= 9 && digits.length <= 10;
}

/** 有填但格式不對的項目：項目 → 說明。 */
export function fillProblems(values: Record<string, string>): Record<string, string> {
  const problems: Record<string, string> = {};
  const name = values[NAME_ITEM]?.trim();
  if (name && !nameOk(name)) problems[NAME_ITEM] = NAME_PROBLEM;
  const phone = values[PHONE_ITEM]?.trim();
  if (phone && !phoneOk(phone)) problems[PHONE_ITEM] = PHONE_PROBLEM;
  return problems;
}
