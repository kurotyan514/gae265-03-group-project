"""切出來的條文在入庫前的檢查：回傳問題清單，不 raise，讓上傳 agent 能逐項顯示。"""

from dataclasses import dataclass
from typing import Literal

from app.ingest.catalog import article_label
from app.ingest.clauses import Chunk


@dataclass(frozen=True)
class Issue:
    level: Literal["warning", "error"]
    message: str


def validate_articles(articles: list[Chunk], *, min_articles: int) -> list[Issue]:
    """error 會擋下入庫；warning 只提醒。"""
    issues: list[Issue] = []
    if len(articles) < min_articles:
        issues.append(
            Issue("error", f"只切出 {len(articles)} 條條文，少於下限 {min_articles}")
        )

    numbers = [c.article_no for c in articles]
    duplicated = sorted({n for n in numbers if numbers.count(n) > 1})
    if duplicated:
        issues.append(Issue("error", f"條號重複：{', '.join(map(str, duplicated))}"))

    for c in articles:
        if not 1 <= c.article_no <= 99:
            issues.append(Issue("error", f"條號超出支援範圍 1–99：{c.article_no}"))
            continue
        label = article_label(c.article_no)
        if not c.text.strip():
            issues.append(Issue("error", f"{label}沒有內容"))
        if not c.article_title.strip():
            issues.append(Issue("warning", f"{label}沒有標題"))
        if c.page_end < c.page_start:
            issues.append(
                Issue("error", f"{label}頁碼不合理：{c.page_start}–{c.page_end}")
            )

    return issues


def repair_articles(articles: list[Chunk]) -> tuple[list[Chunk], list[str]]:
    """程式能安全修的才修：空內容的條文丟掉、超出 1–99 的條號排除、重複條號只留內容最長的一條。

    條文文字一個字都不改；每個動作都回報，讓使用者看得到少了什麼。
    """
    actions: list[str] = []
    kept: list[Chunk] = []
    for c in articles:
        if not c.text.strip():
            actions.append(f"第 {c.article_no} 條沒有內容，已排除")
        elif not 1 <= c.article_no <= 99:
            actions.append(f"條號 {c.article_no} 超出支援範圍 1–99，已排除")
        else:
            kept.append(c)

    best: dict[int, Chunk] = {}
    for c in kept:
        if c.article_no in best:
            actions.append(f"第 {c.article_no} 條重複，只保留內容較長的一條")
            if len(c.text) <= len(best[c.article_no].text):
                continue
        best[c.article_no] = c
    return sorted(best.values(), key=lambda c: c.article_no), actions
