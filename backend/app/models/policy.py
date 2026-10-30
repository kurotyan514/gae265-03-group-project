import uuid
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Column, ForeignKeyConstraint, Index, UniqueConstraint
from sqlmodel import Field

from app.core.config import settings
from app.models.base import BaseTable


class Policy(BaseTable, table=True):
    """保單文件：使用者上傳的保單 PDF，屬於個人資料（ADR-0009）。

    原檔 v1 不保存，也不存原檔名（可能含姓名）；storage_* 留給日後存進使用者的 Google Drive。
    """

    __tablename__ = "policy"  # pyright: ignore[reportAssignmentType]
    # 讓 policy_chunk 等表能用 (policy_id, user_id) 複合外鍵，確保冗餘的 user_id 與保單的擁有者一致
    __table_args__ = (UniqueConstraint("id", "user_id"),)

    user_id: uuid.UUID = Field(foreign_key="user.id", ondelete="CASCADE", index=True)
    display_name: str = Field(
        description="給使用者看的名稱，預設由系統產生，不用原檔名"
    )
    status: str = Field(default="processing", description="processing／ready／failed")
    error_message: str | None = None
    chunk_strategy: str | None = Field(
        default=None,
        description="用了哪一種切法：article（依條號）／page（依頁與段落）",
    )
    page_count: int | None = None
    detected_company: str | None = Field(
        default=None, description="從保單文字偵測到的保險公司，可能不在條款庫"
    )
    detected_product: str | None = Field(
        default=None, description="從保單文字偵測到的商品名，可能不在條款庫"
    )
    storage_provider: str | None = Field(
        default=None, description="原檔存放處（日後 google_drive）；v1 一律為空"
    )
    storage_ref: str | None = Field(
        default=None, description="原檔在 storage_provider 的識別；v1 一律為空"
    )


class PolicyInsurance(BaseTable, table=True):
    """程式從保單文字完全比對到的險種（ADR-0010）；比對不到就沒有資料列。"""

    __tablename__ = "policy_insurance"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (UniqueConstraint("policy_id", "insurance_id"),)

    policy_id: uuid.UUID = Field(foreign_key="policy.id", ondelete="CASCADE")
    insurance_id: uuid.UUID = Field(
        foreign_key="insurance.id", ondelete="CASCADE", index=True
    )


class PolicyChunk(BaseTable, table=True):
    """保單段落：已去識別化的檢索單位。user_id 是檢索時過濾用的冗餘欄位。"""

    __tablename__ = "policy_chunk"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint("policy_id", "idx"),
        ForeignKeyConstraint(
            ["policy_id", "user_id"],
            ["policy.id", "policy.user_id"],
            ondelete="CASCADE",
        ),
    )

    policy_id: uuid.UUID = Field(index=True)
    user_id: uuid.UUID = Field(index=True)
    idx: int = Field(description="段落在這份保單中的順序，從 0 開始")
    page_start: int
    page_end: int
    article_no: int | None = Field(default=None, description="依條號切時的條號")
    content: str = Field(description="已去識別化的內容")


class PolicyChunkEmbedding(BaseTable, table=True):
    """保單段落的向量，做法同 RuleEmbedding：同一段落可有多個模型的向量。"""

    __tablename__ = "policy_chunk_embedding"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint("chunk_id", "model"),
        Index(
            "ix_policy_chunk_embedding_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    chunk_id: uuid.UUID = Field(foreign_key="policy_chunk.id", ondelete="CASCADE")
    model: str
    # 維度固定為 EMBEDDING_DIMENSIONS；改維度要新的 migration 並重建向量
    embedding: list[float] = Field(
        sa_column=Column(Vector(settings.EMBEDDING_DIMENSIONS), nullable=False)
    )


class PolicyEvent(BaseTable, table=True):
    """保單處理的一個步驟，給前端的進度顯示（ADR-0007 的做法）。seq 在同一份保單內遞增。"""

    __tablename__ = "policy_event"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (UniqueConstraint("policy_id", "seq"),)

    policy_id: uuid.UUID = Field(
        foreign_key="policy.id", ondelete="CASCADE", index=True
    )
    seq: int
    step: str = Field(description="extract／deidentify／chunk／embed／import／done")
    status: str = Field(description="running／ok／warning／error")
    message: str
    current: int | None = None
    total: int | None = None
    data: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON(none_as_null=True), nullable=True)
    )
