"""比較紀錄（spec #75）：1-1、1-2 換步驟時存檔、進入時讀回。只能存取自己的紀錄。"""

import uuid
from datetime import date, datetime
from typing import Annotated, Self

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

from app.api.deps import CurrentUser, SessionDep
from app.domain.benefits import Concern
from app.domain.destinations import Destination
from app.models import Comparison

router = APIRouter(tags=["comparisons"])


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
        # ponytail: 用伺服器的日期當今天；伺服器與使用者時區不同時，跨日前後幾小時會差一天
        if self.depart_date < date.today() and not depart_unchanged:
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


async def _own_comparison(
    session: SessionDep, user: CurrentUser, comparison_id: uuid.UUID
) -> Comparison:
    comparison = await session.get(Comparison, comparison_id)
    # 別人的紀錄跟不存在一樣回 404，不洩漏它存在
    if comparison is None or comparison.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到這筆比較紀錄")
    return comparison


@router.post("/comparisons", status_code=status.HTTP_201_CREATED)
async def create_comparison(
    session: SessionDep, user: CurrentUser, body: ComparisonIn
) -> ComparisonOut:
    """1-1 第一次按「下一步」時建立。"""
    comparison = Comparison(user_id=user.id, **body.model_dump())
    session.add(comparison)
    await session.commit()
    return ComparisonOut.model_validate(comparison, from_attributes=True)


@router.get("/comparisons/{comparison_id}")
async def get_comparison(
    session: SessionDep, user: CurrentUser, comparison_id: uuid.UUID
) -> ComparisonOut:
    comparison = await _own_comparison(session, user, comparison_id)
    return ComparisonOut.model_validate(comparison, from_attributes=True)


@router.patch("/comparisons/{comparison_id}")
async def update_comparison(
    session: SessionDep,
    user: CurrentUser,
    comparison_id: uuid.UUID,
    body: ComparisonPatch,
) -> ComparisonOut:
    """換步驟時存檔，可只帶部分欄位。"""
    comparison = await _own_comparison(session, user, comparison_id)
    stored = comparison.model_dump(include=set(ComparisonIn.model_fields))
    try:
        merged = ComparisonIn.model_validate(
            stored | body.model_dump(exclude_unset=True),
            context={"stored_depart_date": comparison.depart_date},
        )
    except ValidationError as e:
        raise RequestValidationError(
            [{**err, "loc": ("body", *err["loc"])} for err in e.errors()]
        ) from e
    comparison.sqlmodel_update(merged.model_dump())
    session.add(comparison)
    await session.commit()
    return ComparisonOut.model_validate(comparison, from_attributes=True)
