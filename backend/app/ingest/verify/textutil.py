"""內容驗證用的文字正規化、中文數字與差異摘要。"""

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

_CN_DIGITS = dict(
    zip("零〇一二三四五六七八九", [0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9], strict=True)
)


def parse_number(text: str) -> int:
    """'12'、'１２'、'十二'、'一百零三' → 整數"""
    text = unicodedata.normalize("NFKC", text)
    if text.isdigit():
        return int(text)
    total = current = 0
    for ch in text:
        if ch == "百":
            total += (current or 1) * 100
            current = 0
        elif ch == "十":
            total += (current or 1) * 10
            current = 0
        else:
            current = _CN_DIGITS[ch]
    return total + current


def normalize(text: str) -> str:
    """比對用：全形半形統一、去掉所有空白與換行。只剩「格式差異」的兩段文字，正規化後會相同。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def diff_ops(expected: str, actual: str) -> list[tuple[str, str, str]]:
    """逐字比對：回傳 (類型, PDF 的字, 條文的字)；類型為 equal／missing／extra／replace。"""
    sm = SequenceMatcher(None, expected, actual, autojunk=False)
    names = {
        "equal": "equal",
        "delete": "missing",
        "insert": "extra",
        "replace": "replace",
    }
    return [
        (names[tag], expected[i1:i2], actual[j1:j2])
        for tag, i1, i2, j1, j2 in sm.get_opcodes()
    ]


def diff_summary(expected: str, actual: str) -> dict[str, Any]:
    ops = [op for op in diff_ops(expected, actual) if op[0] != "equal"]
    return {
        "缺漏字數": sum(len(e) for t, e, _ in ops if t in ("missing", "replace")),
        "多出字數": sum(len(a) for t, _, a in ops if t in ("extra", "replace")),
        "差異處數": len(ops),
        "差異範例": [
            {"missing": f"缺「{e[:30]}」", "extra": f"多「{a[:30]}」"}.get(
                t, f"「{e[:30]}」→「{a[:30]}」"
            )
            for t, e, a in ops[:5]
        ],
    }
