"""數字白名單（ADR-0004）：LLM 說明裡的數字必須出現在程式提供的原文或計算結果裡。

推薦流程與問答流程共用；各自決定「允許的來源文字」是什麼。
"""

import re
from collections.abc import Iterable

# 數字開頭不能緊接英文字母、底線、數字、逗號或小數點（U3、g2_500 是代號，不是金額）
_NUMBER = re.compile(r"(?<![A-Za-z_\d,.])(\d[\d,]*)\s*(萬)?")


def extract_numbers(text: str) -> set[str]:
    """抓出文字裡的數字；「50 萬」換算成 500000，千分位逗號去掉。"""
    found = set()
    for digits, wan in _NUMBER.findall(text):
        digits = digits.replace(",", "")
        if not digits:
            continue
        value = int(digits) * (10000 if wan else 1)
        found.add(str(value))
    return found


def unsupported_numbers(text: str, sources: Iterable[str]) -> list[str]:
    """回傳 text 裡「不在來源文字中」的數字，由小到大（空 list 才算通過）。"""
    allowed: set[str] = set()
    for source in sources:
        allowed |= extract_numbers(source)
    return sorted(extract_numbers(text) - allowed, key=int)
