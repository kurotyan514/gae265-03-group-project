import uuid

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    ForeignKeyConstraint,
    UniqueConstraint,
)
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
        # 事件問答一定綁事件，方案／保單問答不綁
        CheckConstraint(
            "(kind = 'incident_qa') = (incident_id IS NOT NULL)",
            name="kind_matches_incident",
        ),
    )

    user_id: uuid.UUID = Field(foreign_key="user.id", ondelete="CASCADE", index=True)
    policy_id: uuid.UUID | None = Field(default=None, index=True)
    title: str | None = None
    kind: str = Field(
        default="plan_qa",
        description="plan_qa（方案／保單問答）／incident_qa（事件問答）",
    )
    incident_id: uuid.UUID | None = Field(
        default=None, foreign_key="incident.id", ondelete="CASCADE", index=True
    )
    is_draft: bool = Field(
        default=False,
        description="新狀況的對話草稿：追問完成前只是草稿，重開可接續，取消則捨棄",
    )


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
    input_mode: str | None = Field(
        default=None, description="text／voice／quick_reply；助手訊息為空"
    )
    quick_replies: list[str] | None = Field(
        default=None,
        sa_column=Column(JSON(none_as_null=True), nullable=True),
        description="助手提供的快速回覆按鈕",
    )


class MessageCitation(BaseTable, table=True):
    """助手訊息引用的條文（出處由程式從檢索結果寫入，不是 LLM 寫的）。"""

    __tablename__ = "message_citation"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (UniqueConstraint("message_id", "rule_id"),)

    message_id: uuid.UUID = Field(
        foreign_key="message.id", ondelete="CASCADE", index=True
    )
    rule_id: uuid.UUID = Field(foreign_key="insurance_rule.id", ondelete="CASCADE")
    score: float | None = None


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
