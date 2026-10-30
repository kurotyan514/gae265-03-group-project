import uuid
from typing import Any

from sqlalchemy import JSON, Column, ForeignKeyConstraint, UniqueConstraint
from sqlmodel import Field, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.base import BaseTable


class Conversation(BaseTable, table=True):
    """對話：針對一份保單文件，或針對選定的險種（沒上傳保單的那條路）。

    必須綁 policy_id 或至少一筆 ConversationInsurance；跨表無法用 CHECK 約束，
    建立對話時要呼叫 conversation_has_source 驗證。
    """

    __tablename__ = "conversation"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        # 讓 claim_case 能用 (conversation_id, user_id) 複合外鍵
        UniqueConstraint("id", "user_id"),
        # 綁的保單必須屬於同一個使用者；policy_id 為空時不檢查
        ForeignKeyConstraint(
            ["policy_id", "user_id"],
            ["policy.id", "policy.user_id"],
            ondelete="CASCADE",
        ),
    )

    user_id: uuid.UUID = Field(foreign_key="user.id", ondelete="CASCADE", index=True)
    policy_id: uuid.UUID | None = Field(default=None, index=True)
    title: str | None = None


class ConversationInsurance(BaseTable, table=True):
    """選保單那條路：對話針對的險種。"""

    __tablename__ = "conversation_insurance"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (UniqueConstraint("conversation_id", "insurance_id"),)

    conversation_id: uuid.UUID = Field(
        foreign_key="conversation.id", ondelete="CASCADE"
    )
    insurance_id: uuid.UUID = Field(
        foreign_key="insurance.id", ondelete="CASCADE", index=True
    )


class Message(BaseTable, table=True):
    """對話中的一則訊息。seq 在同一個對話內遞增。"""

    __tablename__ = "message"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (UniqueConstraint("conversation_id", "seq"),)

    conversation_id: uuid.UUID = Field(
        foreign_key="conversation.id", ondelete="CASCADE", index=True
    )
    seq: int
    role: str = Field(description="user／assistant")
    content: str
    citations: list[dict[str, Any]] | None = Field(
        default=None,
        sa_column=Column(JSON(none_as_null=True), nullable=True),
        description="回答的出處：保單頁碼或條款條號等，由程式產生",
    )


async def conversation_has_source(
    session: AsyncSession, conversation: Conversation
) -> bool:
    """對話是否綁了保單，或至少一個險種。"""
    if conversation.policy_id is not None:
        return True
    first = await session.exec(
        select(ConversationInsurance.id)
        .where(ConversationInsurance.conversation_id == conversation.id)
        .limit(1)
    )
    return first.first() is not None
