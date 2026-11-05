from typing import Any

from sqlalchemy import JSON, CheckConstraint, Column, LargeBinary
from sqlmodel import Field

from app.models.base import BaseTable


class BundleSplit(BaseTable, table=True):
    """合訂本的拆分清單（ADR-0014）：這份 PDF 裡每個險種從哪一頁哪一行開始。

    以 PDF 內容的雜湊值認定「同一份合訂本」：公司改版就是新檔案，要重新確認。
    清單確認過（confirmed）才能用來入庫；偵測出來還沒確認的是草稿（draft）。
    """

    __tablename__ = "bundle_split"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'confirmed')", name="status_valid"),
    )

    file_hash: str = Field(
        unique=True, index=True, description="PDF 內容的 SHA-256（十六進位）"
    )
    filename: str
    company: str = Field(description="保險公司名稱，用來選驗證的 PDF 版面規則")
    loose_article: bool = Field(
        default=False, description="條號與標題黏在一起（安達：第一條【保險範圍】）"
    )
    status: str = Field(default="draft", description="draft／confirmed")
    pdf: bytes | None = Field(
        default=None,
        sa_column=Column(LargeBinary, nullable=True),
        description="上傳時的原始 PDF（確認與入庫要用）；設定檔匯入的來源沒有，改讀 data/clauses",
    )
    sections: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
        description="依 PDF 順序的區段：code、name、page、anchor、skip、approval_no、approval_date、chapters",
    )
