"""方案保費（易安網試算表，spec #48）：保額或天數不在表上就是沒有報價，不推估（ADR-0004）。

金額單位是元。試算表的提醒：保費是來源原始報價、非公式推算。
"""

from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import distinct
from sqlmodel import col, select

from app.api.deps import SessionDep
from app.domain.plans import load_plans
from app.models import PlanPremium

router = APIRouter(tags=["plan-premiums"])


class PlanPremiumOut(BaseModel):
    plan_code: str
    name: str
    company: str
    premium: int


class PlanPremiumOptionsOut(BaseModel):
    sum_insured: list[int]
    days: list[int]


@router.get("/plan-premiums")
async def list_plan_premiums(
    session: SessionDep,
    sum_insured: Annotated[
        int, Query(description="身故保額（元）", examples=[3_000_000])
    ],
    days: Annotated[int, Query(description="保險天數", examples=[5])],
) -> list[PlanPremiumOut]:
    """有報價的方案與保費，由低到高；沒有報價的方案不出現。"""
    rows = (
        await session.exec(
            select(PlanPremium)
            .where(PlanPremium.sum_insured == sum_insured, PlanPremium.days == days)
            .order_by(col(PlanPremium.premium), col(PlanPremium.plan_code))
        )
    ).all()
    plans = {p.id: p for p in load_plans()}
    return [
        PlanPremiumOut(
            plan_code=r.plan_code,
            name=plans[r.plan_code].name,
            company=plans[r.plan_code].company,
            premium=r.premium,
        )
        for r in rows
    ]


@router.get("/plan-premiums/options")
async def get_plan_premium_options(session: SessionDep) -> PlanPremiumOptionsOut:
    """可選的身故保額（元）與天數，由保費資料產生。"""

    async def distinct_values(column) -> list[int]:
        return list(
            (await session.exec(select(distinct(column)).order_by(column))).all()
        )

    return PlanPremiumOptionsOut(
        sum_insured=await distinct_values(col(PlanPremium.sum_insured)),
        days=await distinct_values(col(PlanPremium.days)),
    )
