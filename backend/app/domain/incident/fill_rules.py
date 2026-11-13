"""送件信空格的格式檢查：被保險人姓名與聯絡電話（前端輸入時也用同一套規則，見 frontend/src/features/package/fillRules.ts）。

只檢查有填的值；沒填的空格由「還有空格不能寄出」那條規則處理。其他項目不檢查。

- 被保險人姓名：中文（含罕用字，CJK 擴充區）或英文字母，中間可以有空格、間隔號（· 或 ‧）、
  連字號（-）、英文撇號（'）；開頭結尾必須是文字；2～50 字。
- 聯絡電話：手機是 09 加 8 位數字；市話要有區碼（02～089 等，可以加括號），號碼中間可以有一個連字號，
  可以加分機（#、分機、ext）。國際碼（+886 等）先不收。
"""

import re

NAME_ITEM = "被保險人姓名"
PHONE_ITEM = "聯絡電話"

# 中文：基本區、擴充 A、相容字、擴充 B～H（罕用字）與「〇」
_HAN = r"〇㐀-䶿一-鿿豈-﫿\U00020000-\U0003134f"
_LETTER = rf"[{_HAN}A-Za-z]"
_NAME = re.compile(rf"{_LETTER}(?:[{_HAN}A-Za-z ·‧\-']*{_LETTER})?")

_MOBILE = re.compile(r"09\d{8}")
# 市話：區碼 0 開頭 2～4 碼（不是 09），可以加括號；號碼 6～8 碼，中間最多一個連字號；可加分機
_LANDLINE = re.compile(
    r"(?:\((?P<area1>0[2-8]\d{0,2})\)|(?P<area2>0[2-8]\d{0,2})-?)"
    r"(?P<local>\d{2,4}-?\d{3,4})"
    r"(?:\s*(?:#|分機|ext\.?\s*)\d{1,6})?",
    re.IGNORECASE,
)

NAME_PROBLEM = (
    "被保險人姓名只能填中文或英文（可以有空格、·、-、'），開頭結尾要是文字，2～50 字"
)
PHONE_PROBLEM = "聯絡電話請填手機（09 開頭共 10 碼）或含區碼的市話"


def name_ok(value: str) -> bool:
    return 2 <= len(value) <= 50 and _NAME.fullmatch(value) is not None


def phone_ok(value: str) -> bool:
    if _MOBILE.fullmatch(value):
        return True
    match = _LANDLINE.fullmatch(value)
    if match is None:
        return False
    area = match.group("area1") or match.group("area2") or ""
    digits = area + match.group("local").replace("-", "")
    # 台灣市話含區碼共 9～10 碼
    return 9 <= len(digits) <= 10


def fill_problems(fills: dict[str, str]) -> list[str]:
    """有填但格式不對的項目的說明，照固定順序；都對就是空的。"""
    problems: list[str] = []
    name = fills.get(NAME_ITEM, "").strip()
    if name and not name_ok(name):
        problems.append(NAME_PROBLEM)
    phone = fills.get(PHONE_ITEM, "").strip()
    if phone and not phone_ok(phone):
        problems.append(PHONE_PROBLEM)
    return problems
