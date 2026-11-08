import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Column, Index, UniqueConstraint
from sqlmodel import Field

from app.core.config import settings
from app.models.base import BaseTable


class Insurance(BaseTable, table=True):
    """險種：有自己的保險公司代碼（insCode）與條款，是問答查詢條文的單位。"""

    __tablename__ = "insurance"  # pyright: ignore[reportAssignmentType]

    code: str = Field(unique=True, index=True, description="保險公司代碼，例如 FUBON01")
    name: str = Field(unique=True)
    approval_no: str | None = Field(
        default=None,
        description="主管機關核准／備查文號，例如「富保業字第1130004861號函備查」；回答時必須附上",
    )
    approval_date: str | None = Field(
        default=None, description="文號的日期（民國年.月.日），例如 113.11.29"
    )
    policy_codes: dict[str, str] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
        description=(
            '章名 → 保單代碼，例如 {"第二章 旅行平安保險": "T068"}；'
            "整份險種沒有章的，用空字串當 key。保單上傳靠它把承保內容表上的代碼對到險種與章"
        ),
    )


class InsuranceRule(BaseTable, table=True):
    """條文：一條一列，不切碎。條號沿用商品條款的條號，所以同一險種可能跳號。"""

    __tablename__ = "insurance_rule"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (UniqueConstraint("insurance_id", "article_no"),)

    insurance_id: uuid.UUID = Field(
        foreign_key="insurance.id", ondelete="CASCADE", index=True
    )
    article_no: int
    chapter: str = Field(description="條文一、條文二…")
    title: str
    content: str
    section: str | None = Field(
        default=None,
        description="真正的章，例如「第二章 旅程取消保險」；附加條款沒有章",
    )
    subsection: str | None = Field(
        default=None,
        description=(
            "章底下的節，例如「第二節 班機延誤保險(定額給付-累進式)」；多數條款沒有節。"
            "有節的章（華南的「第三章 個人海外旅行不便保險」）靠它分出是哪一項保障"
        ),
    )
    source_file: str
    page_start: int
    page_end: int


class RuleEmbedding(BaseTable, table=True):
    """條文的向量。同一條文可以有多個模型的向量，換模型時舊的不必先刪。"""

    __tablename__ = "rule_embedding"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint("rule_id", "model"),
        Index(
            "ix_rule_embedding_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    rule_id: uuid.UUID = Field(foreign_key="insurance_rule.id", ondelete="CASCADE")
    model: str
    # 維度固定為 EMBEDDING_DIMENSIONS；改維度要新的 migration 並重建向量
    embedding: list[float] = Field(
        sa_column=Column(Vector(settings.EMBEDDING_DIMENSIONS), nullable=False)
    )
