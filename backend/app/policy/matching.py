"""險種比對（ADR-0010）：保單文字明確載明險種代碼或全名，且與條款庫完全比對才算。

不做模糊比對：相近但不同的名稱（例如「新旅行平安保險」之於「旅行平安保險」）不會被當成同一個。
LLM 不參與。
"""

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

# 險種代碼：前後不能緊貼英數字，避免從更長的編號裡切出一段
_CODE_RE = re.compile(r"(?<![A-Za-z0-9])(T\d{3}|TA\d{2})(?![A-Za-z0-9])")
# 全名前面可以接公司名，不能接其他中文字（「新」旅行平安保險 ≠ 旅行平安保險）
COMPANY_PREFIXES = ("富邦產物", "富邦產險", "國泰產物", "國泰產險")
# 只用來偵測保單是哪家公司。中信不放進 COMPANY_PREFIXES：條款庫裡中信的險種名稱本身就帶公司名，
# 放進去的話，富邦的「旅行平安保險」會被「中國信託產物旅行平安保險」誤配
DETECTED_COMPANIES = (*COMPANY_PREFIXES, "中國信託產物", "中國信託產險")


@dataclass(frozen=True)
class CatalogInsurance:
    id: object
    code: str
    name: str


def _normalize(text: str) -> str:
    """全形轉半形；這是格式正規化，不是模糊比對。"""
    return unicodedata.normalize("NFKC", text)


def _name_matches(name: str, text: str) -> bool:
    cjk = r"一-鿿"
    prefixes = "|".join(re.escape(p) for p in COMPANY_PREFIXES)
    # 全名的字與字之間容許空白或換行（PDF 排版會折行），但不容許少字或多字
    body = r"\s*".join(re.escape(c) for c in name if not c.isspace())
    pattern = rf"(?:(?<![{cjk}])|(?<=(?:{prefixes})))" + body + rf"(?![{cjk}])"
    return re.search(pattern, text) is not None


def match_insurances(
    text: str, catalog: Iterable[CatalogInsurance]
) -> list[CatalogInsurance]:
    """回傳保單文字載明、且條款庫有的險種，依險種代碼排序。"""
    text = _normalize(text)
    codes = set(_CODE_RE.findall(text))
    matched = [
        i for i in catalog if i.code in codes or _name_matches(_normalize(i.name), text)
    ]
    return sorted(matched, key=lambda i: i.code)


def detect_company(text: str) -> str | None:
    """文字裡最先出現的公司名（只認已知前綴，不猜）。"""
    found = [
        (m.start(), m.group()) for p in DETECTED_COMPANIES if (m := re.search(p, text))
    ]
    return min(found)[1] if found else None
