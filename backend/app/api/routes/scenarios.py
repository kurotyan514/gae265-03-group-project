"""1-4 情境試算（spec #120）：依比較紀錄的推薦、次推薦與卡片保額，回傳 5 個情境頁籤的試算卡片。"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlmodel import col, select

from app.api.deps import CurrentUser, SessionDep
from app.api.routes.comparisons import own_comparison, plan_cards
from app.domain.benefits import Concern
from app.domain.plans import load_plans
from app.domain.scenarios import (
    Article,
    Rules,
    ScenarioOut,
    build_scenarios,
    load_scenario_rules,
)
from app.models import Insurance, InsuranceRule

router = APIRouter(tags=["comparisons"])


@router.get("/comparisons/{comparison_id}/scenarios")
async def get_comparison_scenarios(
    session: SessionDep,
    user: CurrentUser,
    comparison_id: uuid.UUID,
    rules: Annotated[Rules, Depends(load_scenario_rules)],
) -> list[ScenarioOut]:
    """5 個情境頁籤的故事、試算假設與試算卡片；數字全由程式算出，不經 AI（ADR-0004）。"""
    c = await own_comparison(session, user, comparison_id)
    # 沿用 1-3 的卡片：保額沒有報價時回到推薦保額
    quotes, cards = await plan_cards(session, c)
    plans = {p.id: p for p in load_plans()}
    codes = {code for card in cards for code in plans[card.plan_code].insurance_codes}
    rows = await session.exec(
        select(
            Insurance.code,
            Insurance.name,
            InsuranceRule.section,
            InsuranceRule.article_no,
        )
        .join(InsuranceRule, col(InsuranceRule.insurance_id) == Insurance.id)
        .where(col(Insurance.code).in_(codes), col(InsuranceRule.section).is_not(None))
    )
    articles = [
        Article(code, name, section or "", no) for code, name, section, no in rows
    ]
    concerns = [Concern(x) for x in c.concerns]
    return build_scenarios(quotes, concerns, cards, plans, rules, articles)
