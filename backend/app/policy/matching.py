"""險種與方案比對（ADR-0013）：保單文字明確載明險種代碼或全名，且與條款庫完全比對才算；
方案的險種全都比對到，才算比對到這個方案。

不做模糊比對：相近但不同的名稱（例如「新旅行平安保險」之於「旅行平安保險」）不會被當成同一個。
LLM 不參與。
"""

import re
import unicodedata
from collections.abc import Collection, Iterable
from dataclasses import dataclass

from app.domain.plans import Plan

# 險種代碼：前後不能緊貼英數字，避免從更長的編號裡切出一段
_CODE_RE = re.compile(r"(?<![A-Za-z0-9])(T\d{3}|TA\d{2})(?![A-Za-z0-9])")
# 全名前面可以接公司名，不能接其他中文字（「新」旅行平安保險 ≠ 旅行平安保險）
COMPANY_PREFIXES = ("富邦產物", "富邦產險", "國泰產物", "國泰產險")
# 中信不放進 COMPANY_PREFIXES：條款庫裡中信的險種名稱本身就帶公司名，
# 放進去的話，富邦的「旅行平安保險」會被「中國信託產物旅行平安保險」誤配


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


def match_plan(matched_codes: Collection[str], plans: Iterable[Plan]) -> Plan | None:
    """險種全都比對到的方案；有多個時取含險種最多的（最具體的那個），同數量取先出現的。"""
    codes = set(matched_codes)
    full = [
        p for p in plans if p.insurance_codes and codes.issuperset(p.insurance_codes)
    ]
    return max(full, key=lambda p: len(p.insurance_codes), default=None)
