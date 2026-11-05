"""比較紀錄（spec #75）：1-1、1-2 換步驟時存檔、進入時讀回。只能存取自己的紀錄。

存檔時天數或在意事項有變就重算推薦（spec #61、ADR-0021），只存兩個方案與各自選的保額；
保費、額度、推薦理由與比較表在讀取時重算。
"""

import uuid
from datetime import date, datetime
from typing import Annotated, Self
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, status
from fastapi.exceptions import RequestValidationError
from pydantic import (
    AfterValidator,
    BaseModel,
    Field,
    ValidationError,
    ValidationInfo,
    model_validator,
)
from pydantic_core import PydanticCustomError
from sqlmodel import col, select

from app.api.deps import CurrentUser, SessionDep
from app.domain.benefits import Concern
from app.domain.destinations import Destination
from app.domain.recommendation import Benefit, Quotes, RecommendationOut, build, pick
from app.models import Comparison, PlanBenefit, PlanPremium

router = APIRouter(tags=["comparisons"])

# 使用者在台灣：「今天」以台灣日期為準，不看伺服器時區
TAIPEI = ZoneInfo("Asia/Taipei")


def _check_age(age: int) -> int:
    if not 15 <= age <= 80:
        raise PydanticCustomError("age_range", "年齡請填 15～80 的整數。")
    return age


def _check_unique(concerns: list[Concern]) -> list[Concern]:
    if len(set(concerns)) != len(concerns):
        raise PydanticCustomError("concerns_unique", "在意事項不能重複。")
    return concerns


class ComparisonIn(BaseModel):
    destination: Destination
    depart_date: date
    return_date: date
    age: Annotated[int, AfterValidator(_check_age)] = Field(description="15～80 的整數")
    concerns: Annotated[list[Concern], AfterValidator(_check_unique)] = Field(
        default=[], max_length=3, description="依重要程度排序，最多 3 項、不重複"
    )
    note: str = Field(default="", max_length=200, description="其他在意的事")

    @model_validator(mode="after")
    def _check_dates(self, info: ValidationInfo) -> Self:
        # 修改已存的紀錄時，出發日沒變就不檢查是否已過（context 帶已存的出發日）
        stored_depart = (info.context or {}).get("stored_depart_date")
        depart_unchanged = stored_depart == self.depart_date
        today = datetime.now(TAIPEI).date()
        if self.depart_date < today and not depart_unchanged:
            raise PydanticCustomError("depart_past", "出發日要從今天起。")
        if self.return_date < self.depart_date:
            raise PydanticCustomError("return_before_depart", "回程日不能早於出發日。")
        days = (self.return_date - self.depart_date).days + 1
        # 只有 4–10 天有報價（ADR-0018）
        if days < 4:
            raise PydanticCustomError("trip_too_short", "旅遊天數最短 4 天。")
        if days > 10:
            raise PydanticCustomError("trip_too_long", "旅遊天數最長 10 天。")
        return self


class ComparisonPatch(BaseModel):
    """只帶要改的欄位；合併已存的值之後照 ComparisonIn 的規則驗證。"""

    destination: Destination | None = None
    depart_date: date | None = None
    return_date: date | None = None
    age: int | None = Field(default=None, description="15～80 的整數")
    concerns: list[Concern] | None = None
    note: str | None = None
    recommended_sum_insured: int | None = Field(
        default=None,
        description="改推薦方案卡片的身故保額（元）；同一請求改了天數或在意事項時忽略",
    )
    alternative_sum_insured: int | None = Field(
        default=None,
        description="改對照方案（次推薦）卡片的身故保額（元）；同一請求改了天數或在意事項時忽略",
    )


class ComparisonOut(BaseModel):
    id: uuid.UUID
    destination: Destination
    depart_date: date
    return_date: date
    age: int
    concerns: list[Concern]
    note: str
    created_at: datetime
    updated_at: datetime
    recommendation: RecommendationOut | None = Field(
        description="推薦方案、次推薦與比較表；還沒推薦（在意事項是空的）時是 null"
    )


async def _own_comparison(
    session: SessionDep, user: CurrentUser, comparison_id: uuid.UUID
) -> Comparison:
    comparison = await session.get(Comparison, comparison_id)
    # 別人的紀錄跟不存在一樣回 404，不洩漏它存在
    if comparison is None or comparison.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到這筆比較紀錄")
    return comparison


def _days(c: Comparison) -> int:
    return (c.return_date - c.depart_date).days + 1


async def _quotes(session: SessionDep, days: int) -> Quotes:
    premiums = (
        await session.exec(select(PlanPremium).where(PlanPremium.days == days))
    ).all()
    # ponytail: 每次讀整張 plan_benefit（約兩千列），變慢再依方案與保額篩
    benefits = (
        await session.exec(select(PlanBenefit).order_by(col(PlanBenefit.position)))
    ).all()
    by_plan: dict[str, dict[int, int]] = {}
    for p in premiums:
        by_plan.setdefault(p.plan_code, {})[p.sum_insured] = p.premium
    by_pair: dict[tuple[str, int], list[Benefit]] = {}
    for b in benefits:
        by_pair.setdefault((b.plan_code, b.sum_insured), []).append(
            Benefit(b.name, b.category, b.amount)
        )
    return Quotes(by_plan, by_pair)


async def _recommend(session: SessionDep, comparison: Comparison) -> None:
    """重算推薦，兩張卡片的保額回到各自的推薦保額；在意事項是空的時清空。"""
    picked = None
    if comparison.concerns:
        concerns = [Concern(c) for c in comparison.concerns]
        picked = pick(await _quotes(session, _days(comparison)), concerns)
        if picked is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"{_days(comparison)} 天有報價的方案不到兩個，無法推薦（請先 make seed）",
            )
    (rec_code, rec_sum), (alt_code, alt_sum) = picked or ((None, None), (None, None))
    comparison.recommended_plan_code = rec_code
    comparison.recommended_sum_insured = rec_sum
    comparison.alternative_plan_code = alt_code
    comparison.alternative_sum_insured = alt_sum


async def _out(session: SessionDep, comparison: Comparison) -> ComparisonOut:
    recommendation = None
    if (
        comparison.recommended_plan_code
        and comparison.recommended_sum_insured
        and comparison.alternative_plan_code
        and comparison.alternative_sum_insured
    ):
        recommendation = build(
            await _quotes(session, _days(comparison)),
            [Concern(c) for c in comparison.concerns],
            (comparison.recommended_plan_code, comparison.recommended_sum_insured),
            (comparison.alternative_plan_code, comparison.alternative_sum_insured),
        )
    return ComparisonOut.model_validate(
        comparison.model_dump() | {"recommendation": recommendation}
    )


async def _change_sums(
    session: SessionDep, comparison: Comparison, body: ComparisonPatch
) -> None:
    """改卡片的保額：只改該卡片，不重新推薦；保額要是該方案在該天數下有報價的。"""
    cards = [
        (
            "recommended_sum_insured",
            comparison.recommended_plan_code,
            body.recommended_sum_insured,
        ),
        (
            "alternative_sum_insured",
            comparison.alternative_plan_code,
            body.alternative_sum_insured,
        ),
    ]
    cards = [c for c in cards if c[2] is not None]
    if not cards:
        return
    if comparison.recommended_plan_code is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "還沒有推薦方案，請先選在意事項"
        )
    quotes = await _quotes(session, _days(comparison))
    for field, plan_code, sum_insured in cards:
        assert plan_code is not None and sum_insured is not None
        if sum_insured not in quotes.options(plan_code):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"這個方案沒有 {sum_insured / 10000:g} 萬的報價",
            )
        setattr(comparison, field, sum_insured)


@router.post("/comparisons", status_code=status.HTTP_201_CREATED)
async def create_comparison(
    session: SessionDep, user: CurrentUser, body: ComparisonIn
) -> ComparisonOut:
    """1-1 第一次按「下一步」時建立。"""
    comparison = Comparison(user_id=user.id, **body.model_dump())
    await _recommend(session, comparison)
    session.add(comparison)
    await session.commit()
    return await _out(session, comparison)


@router.get("/comparisons/{comparison_id}")
async def get_comparison(
    session: SessionDep, user: CurrentUser, comparison_id: uuid.UUID
) -> ComparisonOut:
    """額度是試算表顯示的金額，不是保證的理賠上限；未列的保障不等於沒有保障。"""
    comparison = await _own_comparison(session, user, comparison_id)
    return await _out(session, comparison)


@router.patch("/comparisons/{comparison_id}")
async def update_comparison(
    session: SessionDep,
    user: CurrentUser,
    comparison_id: uuid.UUID,
    body: ComparisonPatch,
) -> ComparisonOut:
    """換步驟時存檔，可只帶部分欄位；也用來改卡片的保額（只改該卡片，不重新推薦）。"""
    comparison = await _own_comparison(session, user, comparison_id)
    stored = comparison.model_dump(include=set(ComparisonIn.model_fields))
    before = (_days(comparison), comparison.concerns)
    try:
        merged = ComparisonIn.model_validate(
            stored
            | body.model_dump(
                exclude_unset=True, include=set(ComparisonIn.model_fields)
            ),
            context={"stored_depart_date": comparison.depart_date},
        )
    except ValidationError as e:
        raise RequestValidationError(
            [{**err, "loc": ("body", *err["loc"])} for err in e.errors()]
        ) from e
    comparison.sqlmodel_update(merged.model_dump())
    changed = (_days(comparison), comparison.concerns) != before
    # 舊紀錄有在意事項卻沒推薦（推薦功能上線前存的）也補算
    if changed or (comparison.concerns and comparison.recommended_plan_code is None):
        await _recommend(session, comparison)
    else:
        await _change_sums(session, comparison, body)
    session.add(comparison)
    await session.commit()
    return await _out(session, comparison)
