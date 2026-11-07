import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlmodel import col, select

from app.api.deps import CurrentUser, SessionDep
from app.domain.benefits import BenefitCategory
from app.domain.plans import Plan, get_plan, load_plans
from app.models import (
    Conversation,
    ConversationInsurance,
    Insurance,
    PlanBenefit,
    PlanPremium,
)

router = APIRouter(tags=["plans"])


class PlanInsuranceOut(BaseModel):
    code: str
    name: str
    approval_no: str | None
    approval_date: str | None


class PlanOut(BaseModel):
    id: str
    name: str
    insurances: list[PlanInsuranceOut]


class ConversationOut(BaseModel):
    id: uuid.UUID
    title: str | None
    plan_id: str
    insurance_codes: list[str]


class PlanBenefitOut(BaseModel):
    name: str
    category: BenefitCategory | None
    amount: int


class BenefitHighlightOut(BaseModel):
    category: BenefitCategory
    benefits: list[PlanBenefitOut]


class PlanBenefitsOut(BaseModel):
    plan_id: str
    sum_insured: int
    benefits: list[PlanBenefitOut]
    highlights: list[BenefitHighlightOut]


async def _plan_insurances(session: SessionDep, plan: Plan) -> list[Insurance]:
    """方案的險種，順序同設定檔；條款庫缺任何一個就 409（資料不齊，不默默少給）。"""
    rows = (
        await session.exec(
            select(Insurance).where(col(Insurance.code).in_(plan.insurance_codes))
        )
    ).all()
    by_code = {i.code: i for i in rows}
    missing = [c for c in plan.insurance_codes if c not in by_code]
    if missing:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"方案「{plan.name}」的險種不在條款庫：{', '.join(missing)}",
        )
    return [by_code[c] for c in plan.insurance_codes]


@router.get("/plans")
async def list_plans(session: SessionDep) -> list[PlanOut]:
    """可選的方案與其險種（固定測試方案，資料來源見 app/domain/plans.py）。"""
    return [
        PlanOut(
            id=plan.id,
            name=plan.name,
            insurances=[
                PlanInsuranceOut(
                    code=i.code,
                    name=i.name,
                    approval_no=i.approval_no,
                    approval_date=i.approval_date,
                )
                for i in await _plan_insurances(session, plan)
            ],
        )
        for plan in load_plans()
    ]


@router.post("/plans/{plan_id}/conversations", status_code=status.HTTP_201_CREATED)
async def create_plan_conversation(
    session: SessionDep, user: CurrentUser, plan_id: str
) -> ConversationOut:
    """選定方案：建立對話，並把方案的險種寫入 conversation_insurance。"""
    plan = get_plan(plan_id)
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"找不到方案「{plan_id}」")
    insurances = await _plan_insurances(session, plan)
    conversation = Conversation(user_id=user.id, title=plan.name)
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
        plan_id=plan.id,
        insurance_codes=list(plan.insurance_codes),
    )


class PlanSumInsuredOptionsOut(BaseModel):
    plan_id: str
    sum_insured: list[int]


@router.get("/plans/{plan_id}/sum-insured-options")
async def list_plan_sum_insured_options(
    session: SessionDep, plan_id: str
) -> PlanSumInsuredOptionsOut:
    """方案可投保的身故保額（元），由小到大；各方案不同（ADR-0018）。方案不存在回 404。"""
    if get_plan(plan_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"找不到方案「{plan_id}」")
    values = (
        await session.exec(
            select(PlanPremium.sum_insured)
            .where(PlanPremium.plan_code == plan_id)
            .distinct()
            .order_by(col(PlanPremium.sum_insured))
        )
    ).all()
    return PlanSumInsuredOptionsOut(plan_id=plan_id, sum_insured=list(values))


@router.get("/plans/{plan_id}/benefits")
async def list_plan_benefits(
    session: SessionDep,
    plan_id: str,
    sum_insured: Annotated[
        int, Query(description="身故保額（元）", examples=[3_000_000])
    ],
) -> PlanBenefitsOut:
    """方案在某身故保額下的完整保障明細，與依保障類別分組的保障重點（金額單位：元）。

    額度是試算表顯示的金額，不是保證的理賠上限；未列的保障不等於沒有保障。
    """
    rows = (
        await session.exec(
            select(PlanBenefit)
            .where(
                PlanBenefit.plan_code == plan_id, PlanBenefit.sum_insured == sum_insured
            )
            .order_by(col(PlanBenefit.position))
        )
    ).all()
    if not rows:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"方案「{plan_id}」沒有身故保額 {sum_insured} 元的保障資料",
        )
    benefits = [
        PlanBenefitOut(
            name=r.name,
            category=BenefitCategory(r.category) if r.category else None,
            amount=r.amount,
        )
        for r in rows
    ]
    return PlanBenefitsOut(
        plan_id=plan_id,
        sum_insured=sum_insured,
        benefits=benefits,
        highlights=[
            BenefitHighlightOut(category=c, benefits=items)
            for c in BenefitCategory
            if (items := [b for b in benefits if b.category == c])
        ],
    )
