"""長條文的子塊：關鍵字檢索（BM25）用。

條文一條一列、不切碎是刻意的（ADR-0005），所以向量與引用都以整條為單位。但 BM25 對很長的條文會被
長度正規化稀釋，藏在除外責任某一款裡的短句很難被關鍵字找到；把長條文（≥ `CHILD_MIN_CHARS` 字）依「款」切成
子塊、只給 BM25 用，命中就回到整條。評估見 docs/reports/subchunk-2026-11-09.md。
"""

import re

CHILD_MIN_CHARS = 800  # 短於這個長度的條文不切（切太小會讓短條文的檢索變差）
CHILD_CHARS = 400  # 每個子塊約這個字數
MARKER = re.compile(r"^(?:[一二三四五六七八九十]+、|[（(][一二三四五六七八九十]+[)）])")
_TOP_MARKER = re.compile(r"^[一二三四五六七八九十]+、")


def windows(content: str, size: int) -> list[str]:
    """依行數累積到約 size 字就切一塊，重疊一行。"""
    lines = [ln.strip() for ln in content.split("\n") if ln.strip()]
    out: list[str] = []
    cur: list[str] = []
    n = 0
    for ln in lines:
        if cur and n + len(ln) > size:
            out.append("".join(cur))
            cur = cur[-1:]
            n = len(cur[0])
        cur.append(ln)
        n += len(ln)
    if cur:
        out.append("".join(cur))
    return out


def by_clause(content: str, size: int = CHILD_CHARS) -> list[str]:
    """依「款」（一、二、）切：導言（第一款之前的行）附在每一塊前面，太長的款再依行數切；沒有款就依行數切。"""
    lines = [ln.strip() for ln in content.split("\n") if ln.strip()]
    first = next((i for i, ln in enumerate(lines) if MARKER.match(ln)), None)
    if first is None:
        return windows(content, size)
    lead = "".join(lines[:first][:2])
    groups: list[list[str]] = []
    for ln in lines[first:]:
        if _TOP_MARKER.match(ln) or not groups:
            groups.append([])
        groups[-1].append(ln)
    out: list[str] = []
    for g in groups:
        body = "".join(g)
        for part in windows("\n".join(g), size) if len(body) > size else [body]:
            out.append(f"{lead}…{part}" if lead else part)
    return out


def child_texts(head: str, content: str) -> list[str]:
    """長條文的子塊文字（每塊前面帶標頭：險種、章、節、條序、標題）；不夠長就是空的，由整條代表。"""
    if len(content) < CHILD_MIN_CHARS:
        return []
    return [f"{head}\n{part}" for part in by_clause(content)]
