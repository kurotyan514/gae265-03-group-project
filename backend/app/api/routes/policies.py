"""保單上傳（ADR-0013）：收 PDF、抽文字，與條款庫的險種與方案比對；比對到才建立保單。

原檔、原文與原檔名都不保存。使用者再從保單選險種詢問，或以該對話建立理賠待辦清單。
"""

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlmodel import col, select

from app.api.deps import CurrentUser, SessionDep
from app.api.routes.plans import ConversationOut
from app.core.config import settings
from app.domain.plans import get_plan, load_plans
from app.models import (
    Conversation,
    ConversationInsurance,
    Insurance,
    Policy,
    PolicyInsurance,
)
from app.policy.extract import ExtractionError, PdfTextExtractor
from app.policy.matching import CatalogInsurance, match_insurances, match_plan

router = APIRouter(tags=["policies"])

PDF_MIME = "application/pdf"
NO_MATCH_MESSAGE = (
    "條款庫裡沒有這份保單的商品方案，無法解析；請確認保單是否為本系統收錄的方案"
)


class PolicyInsuranceOut(BaseModel):
    code: str
    name: str


class PolicyOut(BaseModel):
    id: uuid.UUID
    display_name: str
    plan_id: str
    plan_name: str
    insurances: list[PolicyInsuranceOut]
    created_at: datetime


async def _policy_out(session: SessionDep, policy: Policy) -> PolicyOut:
    insurances = (
        await session.exec(
            select(Insurance)
            .join(
                PolicyInsurance, col(PolicyInsurance.insurance_id) == col(Insurance.id)
            )
            .where(PolicyInsurance.policy_id == policy.id)
            .order_by(col(Insurance.code))
        )
    ).all()
    plan = get_plan(policy.plan_id)
    return PolicyOut(
        id=policy.id,
        display_name=policy.display_name,
        plan_id=policy.plan_id,
        plan_name=plan.name if plan else policy.plan_id,
        insurances=[PolicyInsuranceOut(code=i.code, name=i.name) for i in insurances],
        created_at=policy.created_at,
    )


async def _own_policy(
    session: SessionDep, user: CurrentUser, policy_id: uuid.UUID
) -> Policy:
    policy = await session.get(Policy, policy_id)
    # 別人的保單跟不存在一樣回 404，不洩漏它存在
    if policy is None or policy.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到這份保單")
    return policy


@router.post("/policies", status_code=status.HTTP_201_CREATED)
async def create_policy(
    session: SessionDep,
    user: CurrentUser,
    file: Annotated[UploadFile, File(description="保單 PDF（文字型）")],
) -> PolicyOut:
    """上傳保單 PDF，與條款庫比對險種與方案。比對不到方案回 422，不留下任何資料。"""
    limit = settings.POLICY_MAX_UPLOAD_MB * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"檔案超過 {settings.POLICY_MAX_UPLOAD_MB} MB",
        )
    if file.content_type != PDF_MIME or not data.startswith(b"%PDF-"):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "只接受 PDF 檔")
    try:
        pages = await asyncio.to_thread(PdfTextExtractor().extract, data)
    except ExtractionError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e

    catalog = [
        CatalogInsurance(i.id, i.code, i.name)
        for i in (await session.exec(select(Insurance))).all()
    ]
    matched = match_insurances("\n".join(p.text for p in pages), catalog)
    plan = match_plan([i.code for i in matched], load_plans())
    if plan is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, NO_MATCH_MESSAGE)

    policy = Policy(
        user_id=user.id,
        # 不用原檔名（可能含姓名）
        display_name=f"{plan.name} {datetime.now(UTC):%Y-%m-%d %H:%M}",
        plan_id=plan.id,
    )
    session.add(policy)
    await session.flush()
    session.add_all(
        PolicyInsurance(policy_id=policy.id, insurance_id=i.id)  # pyright: ignore[reportArgumentType]
        for i in matched
        if i.code in plan.insurance_codes
    )
    await session.commit()
    return await _policy_out(session, policy)


@router.get("/policies")
async def list_policies(session: SessionDep, user: CurrentUser) -> list[PolicyOut]:
    """我的保單，新的在前。"""
    policies = (
        await session.exec(
            select(Policy)
            .where(Policy.user_id == user.id)
            .order_by(col(Policy.created_at).desc())
        )
    ).all()
    return [await _policy_out(session, p) for p in policies]


@router.get("/policies/{policy_id}")
async def get_policy(
    session: SessionDep, user: CurrentUser, policy_id: uuid.UUID
) -> PolicyOut:
    return await _policy_out(session, await _own_policy(session, user, policy_id))


@router.post("/policies/{policy_id}/conversations", status_code=status.HTTP_201_CREATED)
async def create_policy_conversation(
    session: SessionDep, user: CurrentUser, policy_id: uuid.UUID
) -> ConversationOut:
    """選這份保單發問：建立對話，險種取自保單比對到的方案。理賠待辦清單也綁在這個對話上。"""
    policy = await _own_policy(session, user, policy_id)
    insurances = (
        await session.exec(
            select(Insurance)
            .join(
                PolicyInsurance, col(PolicyInsurance.insurance_id) == col(Insurance.id)
            )
            .where(PolicyInsurance.policy_id == policy.id)
            .order_by(col(Insurance.code))
        )
    ).all()
    conversation = Conversation(
        user_id=user.id, policy_id=policy.id, title=policy.display_name
    )
    session.add(conversation)
    await session.flush()
    session.add_all(
        ConversationInsurance(conversation_id=conversation.id, insurance_id=i.id)
        for i in insurances
    )
    await session.commit()
    return ConversationOut(
        id=conversation.id,
        title=conversation.title,
        plan_id=policy.plan_id,
        insurance_codes=[i.code for i in insurances],
    )
