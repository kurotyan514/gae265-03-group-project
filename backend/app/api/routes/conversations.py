import datetime as dt
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import CurrentUser, SessionDep
from app.core.llm import get_chat_model
from app.domain.chat import answer_question
from app.models import (
    Conversation,
    ConversationInsurance,
    Insurance,
    InsuranceRule,
    Message,
    MessageCitation,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["conversations"])

MAX_QUESTION_LENGTH = 1000


def answer_model() -> BaseChatModel:
    """問答用的 chat model；測試用 dependency_overrides 換成 fake。"""
    return get_chat_model()


AnswerModel = Annotated[BaseChatModel, Depends(answer_model)]


class ConversationSummaryOut(BaseModel):
    id: uuid.UUID
    title: str | None
    policy_id: uuid.UUID | None
    insurance_codes: list[str]
    created_at: dt.datetime


class CitationOut(BaseModel):
    rule_id: uuid.UUID
    insurance_code: str
    insurance_name: str
    article_no: int
    title: str
    section: str | None
    page_start: int
    page_end: int
    excerpt: str = Field(description="條款原文")
    score: float | None


class MessageOut(BaseModel):
    id: uuid.UUID
    seq: int
    role: str = Field(description="user／assistant")
    content: str
    created_at: dt.datetime
    citations: list[CitationOut]


class MessageIn(BaseModel):
    content: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=MAX_QUESTION_LENGTH
        ),
    ]


async def _own_conversation(
    session: AsyncSession, user: CurrentUser, conversation_id: uuid.UUID
) -> Conversation:
    """別人的對話、事件問答的對話，一律當作不存在。"""
    conversation = (
        await session.exec(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user.id,
                Conversation.kind == "plan_qa",
            )
        )
    ).first()
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到對話")
    return conversation


async def _codes(session: AsyncSession, conversation_ids: list[uuid.UUID]):
    if not conversation_ids:
        return {}
    rows = (
        await session.exec(
            select(ConversationInsurance.conversation_id, Insurance.code)
            .join(
                Insurance, col(Insurance.id) == col(ConversationInsurance.insurance_id)
            )
            .where(col(ConversationInsurance.conversation_id).in_(conversation_ids))
            .order_by(Insurance.code)
        )
    ).all()
    codes: dict[uuid.UUID, list[str]] = {i: [] for i in conversation_ids}
    for conversation_id, code in rows:
        codes[conversation_id].append(code)
    return codes


async def _message_outs(
    session: AsyncSession, messages: list[Message]
) -> list[MessageOut]:
    rows = (
        await session.exec(
            select(MessageCitation, InsuranceRule, Insurance)
            .join(InsuranceRule, col(InsuranceRule.id) == col(MessageCitation.rule_id))
            .join(Insurance, col(Insurance.id) == col(InsuranceRule.insurance_id))
            .where(col(MessageCitation.message_id).in_([m.id for m in messages]))
            .order_by(
                col(MessageCitation.score).desc().nulls_last(),
                col(InsuranceRule.article_no),
            )
        )
    ).all()
    cited: dict[uuid.UUID, list[CitationOut]] = {m.id: [] for m in messages}
    for citation, rule, insurance in rows:
        cited[citation.message_id].append(
            CitationOut(
                rule_id=rule.id,
                insurance_code=insurance.code,
                insurance_name=insurance.name,
                article_no=rule.article_no,
                title=rule.title,
                section=rule.section,
                page_start=rule.page_start,
                page_end=rule.page_end,
                excerpt=rule.content,
                score=citation.score,
            )
        )
    return [
        MessageOut(
            id=m.id,
            seq=m.seq,
            role=m.role,
            content=m.content,
            created_at=m.created_at,
            citations=cited[m.id],
        )
        for m in messages
    ]


async def _next_seq(session: AsyncSession, conversation_id: uuid.UUID) -> int:
    # 鎖住對話列，同一個對話同時送出時 seq 不會重複（交易結束才放開）
    await session.exec(
        select(Conversation.id)
        .where(Conversation.id == conversation_id)
        .with_for_update()
    )
    return (
        await session.exec(
            select(func.coalesce(func.max(Message.seq), 0) + 1).where(
                Message.conversation_id == conversation_id
            )
        )
    ).one()


@router.get("/conversations")
async def list_conversations(
    session: SessionDep, user: CurrentUser
) -> list[ConversationSummaryOut]:
    """我的方案／保單問答對話，新的在前。"""
    conversations = (
        await session.exec(
            select(Conversation)
            .where(Conversation.user_id == user.id, Conversation.kind == "plan_qa")
            .order_by(col(Conversation.created_at).desc())
        )
    ).all()
    codes = await _codes(session, [c.id for c in conversations])
    return [
        ConversationSummaryOut(
            id=c.id,
            title=c.title,
            policy_id=c.policy_id,
            insurance_codes=codes[c.id],
            created_at=c.created_at,
        )
        for c in conversations
    ]


@router.get("/conversations/{conversation_id}/messages")
async def get_conversation_messages(
    session: SessionDep, user: CurrentUser, conversation_id: uuid.UUID
) -> list[MessageOut]:
    """對話歷史，依送出順序；助手訊息附出處。"""
    conversation = await _own_conversation(session, user, conversation_id)
    messages = (
        await session.exec(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(col(Message.seq))
        )
    ).all()
    return await _message_outs(session, list(messages))


@router.post("/conversations/{conversation_id}/messages")
async def send_conversation_message(
    session: SessionDep,
    user: CurrentUser,
    model: AnswerModel,
    conversation_id: uuid.UUID,
    body: MessageIn,
) -> MessageOut:
    """送出一則提問，一次回完整回答（不串流）。回答只依對話綁的險種條文，數字經白名單檢查。"""
    conversation = await _own_conversation(session, user, conversation_id)
    codes = (await _codes(session, [conversation.id]))[conversation.id]

    answer = await answer_question(session, model, body.content, codes)

    # 提問與回答在同一個交易寫入：問答中途失敗不會留下沒有回覆的提問
    first_seq = await _next_seq(session, conversation.id)
    session.add(
        Message(
            conversation_id=conversation.id,
            seq=first_seq,
            role="user",
            content=body.content,
            input_mode="text",
        )
    )
    reply = Message(
        conversation_id=conversation.id,
        seq=first_seq + 1,
        role="assistant",
        content=answer.content,
    )
    session.add(reply)
    await session.flush()
    session.add_all(
        MessageCitation(message_id=reply.id, rule_id=h.rule_id, score=h.score)
        for h in answer.hits
    )
    await session.commit()
    return (await _message_outs(session, [reply]))[0]
