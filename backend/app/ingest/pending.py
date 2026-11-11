"""待確認條文：內容驗證沒通過、停在切塊階段的條文。

存在 `ingest_job.pending_rules`（既有的 JSON 欄位，不需要 migration）。
每一條有自己的狀態，管理者逐條決定放行、修改文字或刪除；全部處理完工作就結束，欄位清空。
舊格式（只有條文欄位、沒有 status）讀進來一律視為待處理。
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.ingest.catalog import ParsedRule
from app.models import IngestJob

Status = Literal["pending", "released", "deleted"]


class PendingArticle(BaseModel):
    insurance_code: str
    article_no: int
    chapter: str
    title: str
    content: str
    section: str | None = None
    subsection: str | None = None
    source_file: str
    page_start: int
    page_end: int
    status: Status = "pending"
    # 驗證沒通過的原因（內容驗證的發現，已轉成可存進 JSON 的格式）
    findings: list[dict[str, Any]] = Field(default_factory=list)
    edited: bool = False

    @classmethod
    def from_rule(
        cls, rule: ParsedRule, findings: list[dict[str, Any]] | None = None
    ) -> PendingArticle:
        return cls(
            insurance_code=rule.insurance_code,
            article_no=rule.article_no,
            chapter=rule.chapter,
            title=rule.title,
            content=rule.content,
            section=rule.section,
            subsection=rule.subsection,
            source_file=rule.source_file,
            page_start=rule.page_start,
            page_end=rule.page_end,
            findings=findings or [],
        )

    def to_rule(self) -> ParsedRule:
        return ParsedRule(
            insurance_code=self.insurance_code,
            article_no=self.article_no,
            chapter=self.chapter,
            title=self.title,
            content=self.content,
            section=self.section,
            subsection=self.subsection,
            source_file=self.source_file,
            page_start=self.page_start,
            page_end=self.page_end,
        )


def load_pending(job: IngestJob) -> list[PendingArticle]:
    return [PendingArticle.model_validate(r) for r in job.pending_rules or []]


def store_pending(job: IngestJob, articles: list[PendingArticle]) -> None:
    """整個換成新的 list，SQLAlchemy 才看得到 JSON 欄位變了。"""
    job.pending_rules = [a.model_dump() for a in articles] or None


def count_by_status(articles: list[PendingArticle]) -> dict[str, int]:
    return {
        s: sum(1 for a in articles if a.status == s)
        for s in ("pending", "released", "deleted")
    }
