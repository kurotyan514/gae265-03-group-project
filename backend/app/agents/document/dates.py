"""從文件的一行字讀出日期，判斷是否在保險期間內（#233 泰國醫療 demo）。

日期由程式讀，不經 LLM（ADR-0004）。支援：
- 西元「2026-07-08」「2026/7/8」「2026.07.08」「2026年7月8日」
- 日／月／年與月／日／年「08/07/2026」：分不出哪一種時兩種都算候選
- 英文月份「8 Jul 2026」「08 JUL 2026」「July 8, 2026」
- 泰國月份縮寫「8 ก.ค. 2569」
- 泰國佛曆（年份大於 2400，減 543）、民國年（年份小於 200，加 1911）

讀不出日期就回空的，由呼叫端決定（合格規範只在讀得出日期時才判斷期間）。
"""

import re
from datetime import date

_MONTHS = {
    m: i
    for i, m in enumerate(
        (
            "jan",
            "feb",
            "mar",
            "apr",
            "may",
            "jun",
            "jul",
            "aug",
            "sep",
            "oct",
            "nov",
            "dec",
        ),
        1,
    )
}
_THAI_MONTHS = {
    m: i
    for i, m in enumerate(
        (
            "ม.ค",
            "ก.พ",
            "มี.ค",
            "เม.ย",
            "พ.ค",
            "มิ.ย",
            "ก.ค",
            "ส.ค",
            "ก.ย",
            "ต.ค",
            "พ.ย",
            "ธ.ค",
        ),
        1,
    )
}

# 年在前：2026-07-08、2026年7月8日、民國 115/07/08
_YMD = re.compile(r"(?<!\d)(\d{2,4})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})(?!\d)")
# 年在後：08/07/2026（日月或月日分不出來）
_XYY = re.compile(r"(?<!\d)(\d{1,2})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{4})(?!\d)")
# 英文月份：8 Jul 2026、July 8, 2026
_D_MON_Y = re.compile(r"(?<!\d)(\d{1,2})\s*([A-Za-z]{3})[A-Za-z]*\.?,?\s*(\d{4})(?!\d)")
_MON_D_Y = re.compile(r"\b([A-Za-z]{3})[A-Za-z]*\.?\s+(\d{1,2}),?\s*(\d{4})(?!\d)")
_THAI = re.compile(
    r"(?<!\d)(\d{1,2})\s*("
    + "|".join(re.escape(m) for m in _THAI_MONTHS)
    + r")\.?\s*(\d{4})"
)


def _year(y: int) -> int:
    if y > 2400:  # 泰國佛曆
        return y - 543
    if y < 200:  # 民國年
        return y + 1911
    return y


def _make(y: int, m: int, d: int) -> date | None:
    try:
        return date(_year(y), m, d)
    except ValueError:
        return None


def dates_in(text: str) -> set[date]:
    """一行字裡所有可能的日期（分不出日月順序時兩種都列）。"""
    found: set[date | None] = set()
    for y, m, d in _YMD.findall(text):
        if len(y) != 3 and len(y) != 4:
            continue
        found.add(_make(int(y), int(m), int(d)))
    for a, b, y in _XYY.findall(text):
        found.add(_make(int(y), int(b), int(a)))  # 日／月／年
        found.add(_make(int(y), int(a), int(b)))  # 月／日／年
    for d, mon, y in _D_MON_Y.findall(text):
        if (m := _MONTHS.get(mon.lower())) is not None:
            found.add(_make(int(y), m, int(d)))
    for mon, d, y in _MON_D_Y.findall(text):
        if (m := _MONTHS.get(mon.lower())) is not None:
            found.add(_make(int(y), m, int(d)))
    for d, mon, y in _THAI.findall(text):
        found.add(_make(int(y), _THAI_MONTHS[mon], int(d)))
    return {d for d in found if d is not None}


def outside_period(lines: list[str], start: date, end: date) -> bool:
    """讀得出日期、而且沒有一個落在保險期間內，才算在期間外；讀不出日期回 False。"""
    candidates = {d for line in lines for d in dates_in(line)}
    return bool(candidates) and not any(start <= d <= end for d in candidates)
