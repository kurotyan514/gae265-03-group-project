"""方案保費（易安網試算表，spec #48）：保額或天數不在表上就是沒有報價，不推估（ADR-0004）。

金額單位是元。試算表的提醒：保費是來源原始報價、非公式推算。
"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlmodel import col, select

from app.api.deps import SessionDep
from app.domain.benefits import CONCERN_BENEFITS, Concern
from app.domain.plans import load_plans
from app.models import PlanBenefit, PlanPremium

router = APIRouter(tags=["plan-premiums"])


class PlanPremiumOut(BaseModel):
    plan_code: str
    name: str
    company: str
    premium: int
    concern_amounts: dict[str, int] | None = Field(
        None,
        description="有帶 concerns 才有：在意事項 → 對照到的保障項目額度加總（元），沒有就是 0",
    )


class PlanPremiumOptionsOut(BaseModel):
    sum_insured: list[int]
    days: list[int]


def _parse_concerns(text: str) -> list[Concern]:
    names = [n.strip() for n in text.split(",") if n.strip()]
    unknown = [n for n in names if n not in Concern]
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"不認得的在意事項：{', '.join(unknown)}（可選：{', '.join(Concern)}）",
        )
    return [Concern(n) for n in names]


@router.get("/plan-premiums", response_model_exclude_none=True)
async def list_plan_premiums(
    session: SessionDep,
    sum_insured: Annotated[
        int, Query(description="身故保額（元）", examples=[3_000_000])
    ],
    days: Annotated[int, Query(description="保險天數", examples=[5])],
    concerns: Annotated[
        str | None,
        Query(description="在意事項，逗號分隔", examples=["班機延誤,行李"]),
    ] = None,
) -> list[PlanPremiumOut]:
    """有報價的方案與保費，由低到高；沒有報價的方案不出現。

    帶 `concerns` 時每個方案多回 `concern_amounts`：額度是試算表顯示的金額，不是保證的理賠上限。
    """
    wanted = _parse_concerns(concerns) if concerns is not None else None
    rows = (
        await session.exec(
            select(PlanPremium)
            .where(PlanPremium.sum_insured == sum_insured, PlanPremium.days == days)
            .order_by(col(PlanPremium.premium), col(PlanPremium.plan_code))
        )
    ).all()
    amounts: dict[str, dict[str, int]] = {}
    if wanted is not None:
        names = set().union(*(CONCERN_BENEFITS[c] for c in wanted))
        benefits = (
            await session.exec(
                select(PlanBenefit).where(
                    PlanBenefit.sum_insured == sum_insured,
                    col(PlanBenefit.name).in_(names),
                )
            )
        ).all()
        amounts = {
            r.plan_code: {
                c: sum(
                    b.amount
                    for b in benefits
                    if b.plan_code == r.plan_code and b.name in CONCERN_BENEFITS[c]
                )
                for c in wanted
            }
            for r in rows
        }
    plans = {p.id: p for p in load_plans()}
    return [
        PlanPremiumOut(
            plan_code=r.plan_code,
            name=plans[r.plan_code].name,
            company=plans[r.plan_code].company,
            premium=r.premium,
            concern_amounts=amounts.get(r.plan_code),
        )
        for r in rows
    ]


@router.get("/plan-premiums/options")
async def get_plan_premium_options(session: SessionDep) -> PlanPremiumOptionsOut:
    """可選的身故保額（元）與天數，由保費資料產生。"""

    async def distinct_values(column) -> list[int]:
        return list(
            (await session.exec(select(column).distinct().order_by(column))).all()
        )

    return PlanPremiumOptionsOut(
        sum_insured=await distinct_values(col(PlanPremium.sum_insured)),
        days=await distinct_values(col(PlanPremium.days)),
    )
