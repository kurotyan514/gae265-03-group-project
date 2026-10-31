"""去識別化（ADR-0009）：純程式規則，個資在送進 embedding、LLM、log 之前先遮蔽。

做法：
1. 「標籤：值」取出姓名，再把這些姓名在全文取代（收據、頁尾常單獨印出姓名）。
2. 標籤後面的身分證字號、保單號碼、電話、地址等直接遮蔽。
3. 不依賴標籤的格式：身分證字號、手機與市話、email、地址、含英數混合的長編號。

已知限制：沒有緊鄰標籤、格式又不在規則內的姓名會漏掉。除了遮蔽處，文字逐字保留。
遮蔽用的占位文字不含數字（ADR-0004）。
"""

import re

NAME = "〔姓名〕"
ID_NO = "〔身分證字號〕"
POLICY_NO = "〔編號〕"
PHONE = "〔電話〕"
EMAIL = "〔電子郵件〕"
ADDRESS = "〔地址〕"

MIN_ADDRESS_LEN = 6  # 比這短的不像地址，整份取代會誤傷
_CJK_NAME = r"[一-鿿·．]{2,6}"
_LATIN_NAME = r"[A-Za-z][A-Za-z.'-]*(?: [A-Za-z][A-Za-z.'-]*){0,3}"
_VALUE = rf"(?:{_CJK_NAME}|{_LATIN_NAME})"
# 只吃同一行的空白：值在下一行的標籤不能把下一行的標籤當成值
_COLON = r"[ \t\u3000]*[:：][ \t\u3000]*"
# 這些標籤後面接的是姓名；「要保人與被保人關係：」不會命中，因為標籤與冒號之間不能有字
_NAME_LABELS = r"(?:主?被保險人|被保人|要保人|姓名|受益人姓名|聯絡人|法定代理人|負責總繳人|戶名|持卡人)"
_NAME_RE = re.compile(rf"{_NAME_LABELS}{_COLON}({_VALUE})")
# 不是姓名的值（欄位的制式答案）
_NOT_A_NAME = {"本人", "同上", "法定繼承", "法定繼承人", "本公司", "未提供"}
# 條款的名詞定義長得像「被保險人：指…」，不是姓名
_DEFINITION_START = ("指", "係", "為", "是")

_ID_LABEL_RE = re.compile(
    rf"(?:身分證(?:字)?號|身份證(?:字)?號|統一編號)(?:碼)?{_COLON}([A-Za-z0-9]{{6,12}})"
)
_CODE_LABEL_RE = re.compile(
    rf"(?:保險?單號碼|保單號碼|保單編號|業務人員|列印人員){_COLON}([A-Za-z0-9\-]{{4,30}})"
)
_ADDRESS_LABEL_RE = re.compile(
    rf"(?:(?:通訊|戶籍|居住|聯絡|郵寄)?地址|住址){_COLON}([^\s].*?)(?=\s{{2,}}|$)", re.M
)
# 受益人表格：標題列「受益人姓名 關係 備註」與虛線之後的第一列，第一欄是姓名
_BENEFICIARY_HEADER_RE = re.compile(r"受益人姓名.*\n(?:[\s\-]*\n)?")

_TW_ID_RE = re.compile(r"(?<![A-Za-z0-9])[A-Z][12]\d{8}(?![A-Za-z0-9])")
_MOBILE_RE = re.compile(r"(?<!\d)09\d{2}[-\s]?\d{3}[-\s]?\d{3}(?!\d)")
# 市話；0800／0809 是公司的免付費專線，不是個資
_LANDLINE_RE = re.compile(
    r"(?<!\d)(?!08[09]0)\(?0\d{1,2}\)?[-\s]?\d{3,4}[-\s]?\d{3,4}(?:#\d{1,5})?(?!\d)"
)
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_ADDRESS_RE = re.compile(
    r"(?:[一-鿿]{2,3}[縣市])?[一-鿿]{1,4}[區鄉鎮市]"
    r"[一-鿿\d]{0,12}?\d+(?:之\d+)?號(?:\d+樓(?:之\d+)?)?"
)
# 英數混合、至少 9 碼的編號（保單號碼、條碼）；純數字或純英文不會命中
_MIXED_CODE_RE = re.compile(
    r"(?<![A-Za-z0-9])(?=[A-Za-z0-9]*\d)(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{9,}(?![A-Za-z0-9])"
)
_LONG_DIGITS_RE = re.compile(r"(?<!\d)(?!08[09]0)\d{9,}(?!\d)")


def _is_name(value: str) -> bool:
    return value not in _NOT_A_NAME and not value.startswith(_DEFINITION_START)


def _find_names(text: str) -> set[str]:
    names = {v for v in _NAME_RE.findall(text) if _is_name(v)}
    for m in _BENEFICIARY_HEADER_RE.finditer(text):
        row = text[m.end() :].split("\n", 1)[0].strip()
        first = re.split(r"\s{2,}", row)[0] if row else ""
        if re.fullmatch(_VALUE, first) and _is_name(first):
            names.add(first)
    return names


def find_values(layout_texts: list[str]) -> dict[str, set[str]]:
    """從「標籤：值」找出個資的值（占位文字 → 值）。

    用位置排序的文字找，標籤與值才在同一行；找到的值之後會在原本閱讀順序的文字裡逐字取代，
    收據、頁尾常把同一個姓名或保單號碼單獨印出來，也一併遮蔽。
    """
    found: dict[str, set[str]] = {
        NAME: set(),
        ID_NO: set(),
        POLICY_NO: set(),
        ADDRESS: set(),
    }
    for text in layout_texts:
        found[NAME] |= _find_names(text)
        found[ID_NO].update(_ID_LABEL_RE.findall(text))
        found[POLICY_NO].update(_CODE_LABEL_RE.findall(text))
        found[ADDRESS].update(
            a.strip()
            for a in _ADDRESS_LABEL_RE.findall(text)
            if len(a.strip()) >= MIN_ADDRESS_LEN
        )
    return found


def deidentify_text(text: str, values: dict[str, set[str]]) -> str:
    for placeholder, literals in values.items():
        # 長的先換：「九岳」不能先於「廖九岳」把後者拆成「廖〔姓名〕」
        for literal in sorted(literals, key=len, reverse=True):
            text = text.replace(literal, placeholder)
    text = _TW_ID_RE.sub(ID_NO, text)
    text = _EMAIL_RE.sub(EMAIL, text)
    text = _MOBILE_RE.sub(PHONE, text)
    text = _LANDLINE_RE.sub(PHONE, text)
    text = _ADDRESS_RE.sub(ADDRESS, text)
    text = _MIXED_CODE_RE.sub(POLICY_NO, text)
    return _LONG_DIGITS_RE.sub(POLICY_NO, text)


def deidentify_pages(
    pages: list[str], layout_pages: list[str] | None = None
) -> list[str]:
    """整份保單一起處理，標籤找到的值才能套用到每一頁。layout_pages 省略時用 pages 自己找。"""
    values = find_values(pages if layout_pages is None else layout_pages)
    return [deidentify_text(p, values) for p in pages]
