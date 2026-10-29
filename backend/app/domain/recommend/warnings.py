"""條款警示的資料結構。推薦只需要這兩個型別；產生警示的檢索在第 2 階段。"""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Citation:
    company: str
    product: str
    article_no: int
    article_title: str
    page_start: int
    snippet: str


@dataclass(frozen=True)
class ClauseWarning:
    activity: str
    level: Literal["exclusion_found", "not_stated", "unmapped"]
    message: str
    citations: list[Citation]
