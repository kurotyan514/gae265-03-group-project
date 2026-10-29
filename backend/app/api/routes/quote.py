from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from app.domain.pricing.quote import (
    MAX_AGE,
    MAX_TRAVELERS,
    Requirement,
    Traveler,
    quote,
)

router = APIRouter(tags=["quote"])


class TravelerIn(BaseModel):
    age: int = Field(ge=0, le=MAX_AGE, description="足歲")
    rents_car: bool = Field(False, description="是否租車自駕（只有駕駛需要租車欄位）")


class QuoteRequest(BaseModel):
    days: int = Field(ge=1, description="保險涵蓋的總天數")
    travelers: list[TravelerIn] = Field(min_length=1, max_length=MAX_TRAVELERS)
    # 最低保額需求，單位：元；0 表示沒有下限
    illness_medical: int = Field(0, ge=0)
    accident_medical: int = Field(0, ge=0)
    accident_death: int = Field(0, ge=0)
    infectious: bool | None = Field(
        None, description="True 只看含法定傳染病、False 只看不含、不填兩種都看"
    )


class TravelerQuoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    traveler_index: int
    age: int
    column_key: str
    column_label: str
    coverages: dict[str, int]
    price: int


class PlanQuoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    table_id: str
    company: str
    product: str
    plan: str
    infectious_covered: bool
    days: int
    travelers: list[TravelerQuoteOut]
    total: int
    notes: list[str]
    source_file: str
    source_page: int
    valid_from: str


class UnavailableOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    table_id: str
    company: str
    product: str
    plan: str
    reason: str


class QuoteResponse(BaseModel):
    plans: list[PlanQuoteOut] = Field(description="可報價的方案，總價由低到高")
    unavailable: list[UnavailableOut] = Field(description="不可報價的方案與原因")


@router.post("/quote")
async def quote_plans(body: QuoteRequest) -> QuoteResponse:
    plans, unavailable = quote(
        body.days,
        [Traveler(t.age, t.rents_car) for t in body.travelers],
        Requirement(
            illness_medical=body.illness_medical,
            accident_medical=body.accident_medical,
            accident_death=body.accident_death,
            infectious=body.infectious,
        ),
    )
    return QuoteResponse(
        plans=[PlanQuoteOut.model_validate(p) for p in plans],
        unavailable=[UnavailableOut.model_validate(u) for u in unavailable],
    )
