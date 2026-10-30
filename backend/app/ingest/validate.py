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
