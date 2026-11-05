"""合訂本 PDF → 各險種起點的候選邊界（不用 LLM）。

公司官網的合訂本把十幾份商品條款接在一起，每份都從「第一條」重新編號，開頭是商品名稱，
接著是給付項目與核准文號，然後才是第一條。所以：

1. 找出每一個「第一條」標題（編號重新開始的地方）。
2. 往前找這一份的商品名稱：同一家公司的名稱開頭（例如「華南產物」）、最靠近上一份條文結尾的那一行。
3. 輸出候選邊界（頁碼、標題行、標題前幾行），交給管理者確認、改名、標成不收。

這是「候選」不是答案：名稱可能折成兩行、同一頁可能有好幾份、沒有第一條的內容（例如海外急難援助說明）
偵測不到。偵測不到的由管理者在確認畫面補上。
"""

import re
from collections import Counter
from dataclasses import dataclass

from app.ingest.clauses import _lines

_FIRST_ARTICLE = re.compile(r"^第\s*(?:一|1|１)\s*條(?:$|[\s【])")
_ANY_ARTICLE = re.compile(
    r"^第\s*[0-9０-９零〇一二三四五六七八九十百]+\s*條(?:$|[\s【])"
)
# 公司名稱開頭：「華南產物」「臺灣產物」「美商安達產險」
_COMPANY = re.compile(r"^((?:[^\s]{2,4})(?:產物|產險))")
# 標題之後的第一行不再是名稱的延續：括號、給付項目、核准文號與日期
# 名稱最後的型別標示（甲型）（乙型）是名稱的一部分
_TYPE_SUFFIX = re.compile(r"^[(（][^)）]{1,4}型[)）]$")
_TITLE_END = re.compile(
    r"^(?:[【(（]|給付項目|主要給付項目|\d{2,3}\.\d{1,2}\.\d{1,2}|財政部|商品文號|本商品)"
)
WINDOW = 16  # 第一條往前最多看幾行
PREVIEW_LINES = 4


@dataclass(frozen=True)
class Candidate:
    page: int  # 標題行所在頁（從 1 起算）
    anchor: str  # 標題行（第一行）原文
    name: str  # 建議的名稱：標題折行接起來
    first_article_page: int
    preview: list[str]  # 標題之後的前幾行，管理者確認時對照用


def guess_company(flat: list[tuple[int, str]]) -> str | None:
    """整份最常出現的公司名稱開頭。"""
    counts = Counter(m.group(1) for _, ln in flat if (m := _COMPANY.match(ln)))
    return counts.most_common(1)[0][0] if counts else None


def detect_sections(pages: list[str], company: str | None = None) -> list[Candidate]:
    flat = [(n, ln) for n, text in enumerate(pages, start=1) for ln in _lines(text)]
    prefix = company or guess_company(flat)
    if not prefix:
        return []
    candidates: list[Candidate] = []
    floor = 0  # 上一份的第一條之後，標題不會在更前面
    for index, (page, line) in enumerate(flat):
        if not _FIRST_ARTICLE.match(line):
            continue
        start = _title_start(flat, index, floor, prefix)
        floor = index + 1
        if start is None:
            continue
        name = _title_name(flat, start, index)
        candidates.append(
            Candidate(
                page=flat[start][0],
                anchor=flat[start][1],
                name=name,
                first_article_page=page,
                preview=[ln for _, ln in flat[start + 1 : index][:PREVIEW_LINES]],
            )
        )
    return candidates


def _title_start(
    flat: list[tuple[int, str]], first: int, floor: int, prefix: str
) -> int | None:
    """第一條往前，窗口內最早、以公司名稱開頭的那一行；窗口不跨過上一份的條文標題。"""
    lo = max(floor, first - WINDOW)
    for i in range(first - 1, lo - 1, -1):
        if _ANY_ARTICLE.match(flat[i][1]):
            lo = i + 1
            break
    return next(
        (i for i in range(lo, first) if flat[i][1].startswith(prefix)),
        None,
    )


def _title_name(flat: list[tuple[int, str]], start: int, first: int) -> str:
    """標題可能折成兩三行：接到括號、給付項目或核准文號之前。"""
    parts = [flat[start][1]]
    for _, line in flat[start + 1 : first][:3]:
        if _TITLE_END.match(line) and not _TYPE_SUFFIX.match(line):
            break
        parts.append(line)
    return "".join(parts)
