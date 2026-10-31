"""條款勘誤：官網 PDF 與實際保單不同的地方，以保單為準（backend/data/config/clause_errata.json）。

匯入時才套用，PDF 不改。原文比對忽略空白和換行（PDF 抽出的文字有斷行）；
找不到、或不只一處時一律報錯，PDF 換版後勘誤才不會悄悄失效。
只改 old → new 真正不同的那一小段，其餘字元（含換行）保持原樣。
"""

import json
from dataclasses import dataclass, replace
from pathlib import Path

from app.core.config import settings
from app.ingest.catalog import ParsedRule


@dataclass(frozen=True)
class Erratum:
    insurance_code: str
    article_no: int
    old: str  # 官網 PDF 的原文（一小段，在該條內只能出現一次）
    new: str  # 實際保單的文字
    reason: str


def load_errata(path: Path | None = None) -> list[Erratum]:
    path = settings.CONFIG_DIR / "clause_errata.json" if path is None else path
    with open(path, encoding="utf-8") as f:
        return [
            Erratum(
                insurance_code=row["insurance"],
                article_no=row["article_no"],
                old=row["old"],
                new=row["new"],
                reason=row["reason"],
            )
            for row in json.load(f)["errata"]
        ]


def apply_errata(rules: list[ParsedRule], errata: list[Erratum]) -> list[ParsedRule]:
    """回傳套用勘誤後的條文。勘誤指向的險種不在 rules 裡時略過（只匯入部分險種）。"""
    present = {r.insurance_code for r in rules}
    by_key = {(r.insurance_code, r.article_no): i for i, r in enumerate(rules)}
    out = list(rules)
    for e in errata:
        if e.insurance_code not in present:
            continue
        index = by_key.get((e.insurance_code, e.article_no))
        if index is None:
            raise ValueError(f"勘誤找不到條文：{e.insurance_code} 第 {e.article_no} 條")
        try:
            content = replace_ignoring_whitespace(out[index].content, e.old, e.new)
        except ValueError as exc:
            raise ValueError(
                f"勘誤無法套用：{e.insurance_code} 第 {e.article_no} 條：{exc}"
            ) from exc
        out[index] = replace(out[index], content=content)
    return out


def replace_ignoring_whitespace(text: str, old: str, new: str) -> str:
    kept = [(i, ch) for i, ch in enumerate(text) if not ch.isspace()]
    squeezed = "".join(ch for _, ch in kept)
    old_s, new_s = _squeeze(old), _squeeze(new)
    if old_s == new_s:
        raise ValueError("old 與 new 相同")
    found = squeezed.count(old_s)
    if found != 1:
        raise ValueError(
            f"在條文裡找不到原文（PDF 換版了？）：{old}"
            if found == 0
            else f"原文出現 {found} 處，無法確定要改哪一處：{old}"
        )

    start = squeezed.index(old_s)
    limit = min(len(old_s), len(new_s))
    head = 0
    while head < limit and old_s[head] == new_s[head]:
        head += 1
    tail = 0
    while tail < limit - head and old_s[-1 - tail] == new_s[-1 - tail]:
        tail += 1
    removed_from, removed_to = start + head, start + len(old_s) - tail
    inserted = new_s[head : len(new_s) - tail]

    if removed_from == removed_to:  # 純新增：接在前一個字元之後
        at = kept[removed_from - 1][0] + 1
        return text[:at] + inserted + text[at:]
    return (
        text[: kept[removed_from][0]] + inserted + text[kept[removed_to - 1][0] + 1 :]
    )


def _squeeze(s: str) -> str:
    return "".join(ch for ch in s if not ch.isspace())
