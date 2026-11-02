import uuid
from typing import Any

from sqlalchemy import JSON, CheckConstraint, Column, ForeignKeyConstraint
from sqlmodel import Field

from app.models.base import BaseTable


class ClaimCase(BaseTable, table=True):
    """理賠案件：事件釐清完成後建立，綁定一個對話（ADR-0011）。"""

    __tablename__ = "claim_case"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        # 綁的對話必須屬於同一個使用者
        ForeignKeyConstraint(
            ["conversation_id", "user_id"],
            ["conversation.id", "conversation.user_id"],
            ondelete="CASCADE",
        ),
    )

    user_id: uuid.UUID = Field(foreign_key="user.id", ondelete="CASCADE", index=True)
    conversation_id: uuid.UUID = Field(index=True)
    incident_type: str = Field(
        description="medical／baggage／delay／cancellation／liability／other"
    )
    incident: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column(JSON(none_as_null=True), nullable=True),
        description="事件釐清收集到的結構化欄位",
    )
    extra_notes: str | None = Field(
        default=None, description="LLM 依情境追問的答案（自由文字，可能含個資）"
    )
    status: str = Field(default="open", description="open／closed")


class ChecklistItem(BaseTable, table=True):
    """待辦清單的一個項目。id 穩定，供文件辨識日後自動勾選。"""

    __tablename__ = "checklist_item"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        # ADR-0011：擴充項目必須附出處，基本款不需要
        CheckConstraint(
            "kind = 'basic' OR citation IS NOT NULL",
            name="extended_requires_citation",
        ),
    )

    claim_case_id: uuid.UUID = Field(
        foreign_key="claim_case.id", ondelete="CASCADE", index=True
    )
    label: str
    kind: str = Field(description="basic（程式決定）／extended（LLM 提議，附出處）")
    citation: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column(JSON(none_as_null=True), nullable=True),
        description="保單頁碼或條號，程式已驗證存在於原文",
    )
    status: str = Field(default="pending", description="pending／provided")
    sort: int = 0


class ClaimDocument(BaseTable, table=True):
    """【草案，由流程圖的 6 文件辨識負責，欄位待確認】使用者上傳的理賠文件。"""

    __tablename__ = "claim_document"  # pyright: ignore[reportAssignmentType]

    claim_case_id: uuid.UUID = Field(
        foreign_key="claim_case.id", ondelete="CASCADE", index=True
    )
    checklist_item_id: uuid.UUID | None = Field(
        default=None, foreign_key="checklist_item.id", ondelete="SET NULL", index=True
    )
    kind: str | None = Field(default=None, description="辨識出的文件類型")
    status: str = Field(default="pending", description="pending／recognized／failed")


class ClaimSubmission(BaseTable, table=True):
    """【草案，由流程圖的 7 打包追蹤負責，欄位待確認】代寄信與保險公司回覆的追蹤。"""

    __tablename__ = "claim_submission"  # pyright: ignore[reportAssignmentType]

    claim_case_id: uuid.UUID = Field(
        foreign_key="claim_case.id", ondelete="CASCADE", index=True
    )
    status: str = Field(
        default="pending", description="pending／sent／replied／needs_more"
    )
    gmail_thread_id: str | None = None
