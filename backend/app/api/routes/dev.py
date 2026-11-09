"""開發用端點：只在非 production 註冊（見 app.api.main.build_api_router）。

正式環境沒有登入保護，這些端點不存在；第 7 階段後台有 ADMIN_TOKEN 之後再決定要不要開放。
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import CurrentUser, SessionDep
from app.api.routes.insurances import RuleOut, _rule_out
from app.contracts.fakes import seed_sample_catalog
from app.models import Insurance, InsuranceRule, Policy, RuleEmbedding

router = APIRouter(tags=["dev"])


class DevRuleOut(RuleOut):
    embedding_models: list[str] = Field(
        description="這一條已經有向量的 embedding model；空陣列表示還沒算向量"
    )
    embedding_dimensions: int | None = Field(description="向量維度；沒有向量時是 null")


class DevRuleList(BaseModel):
    total: int = Field(description="符合條件的總筆數（不受 limit／offset 影響）")
    items: list[DevRuleOut]


@router.get("/rules")
async def list_all_rules(
    session: SessionDep,
    insurance_code: Annotated[
        str | None, Query(description="只看這個險種", examples=["FUBON05"])
    ] = None,
    q: Annotated[
        str | None, Query(description="標題或內文包含這段文字", examples=["滑雪"])
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DevRuleList:
    """資料庫裡全部條文（依險種代碼、條號排序），含向量狀態。用來核對匯入和給測試網頁瀏覽。"""
    return await rules_with_vector_status(session, insurance_code, q, limit, offset)


async def rules_with_vector_status(
    session: AsyncSession,
    insurance_code: str | None,
    q: str | None,
    limit: int,
    offset: int,
) -> DevRuleList:
    """條文清單加向量狀態；`/rules`（開發用）與 `/admin/rules`（後台，要登入）共用。"""
    embeddings = (
        select(
            col(RuleEmbedding.rule_id),
            func.array_agg(col(RuleEmbedding.model).distinct()).label("models"),
            func.max(func.vector_dims(col(RuleEmbedding.embedding))).label("dims"),
        )
        .group_by(col(RuleEmbedding.rule_id))
        .subquery()
    )
    where = []
    if insurance_code:
        where.append(Insurance.code == insurance_code)
    if q:
        where.append(
            col(InsuranceRule.title).icontains(q, autoescape=True)
            | col(InsuranceRule.content).icontains(q, autoescape=True)
        )

    total = await session.scalar(
        select(func.count()).select_from(InsuranceRule).join(Insurance).where(*where)
    )
    rows = (
        await session.exec(
            select(InsuranceRule, Insurance, embeddings.c.models, embeddings.c.dims)
            .join(Insurance)
            .join(
                embeddings, embeddings.c.rule_id == col(InsuranceRule.id), isouter=True
            )
            .where(*where)
            .order_by(col(Insurance.code), col(InsuranceRule.article_no))
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return DevRuleList(
        total=total or 0,
        items=[
            DevRuleOut(
                **_rule_out(rule, insurance).model_dump(),
                embedding_models=sorted(models or []),
                embedding_dimensions=dims,
            )
            for rule, insurance, models, dims in rows
        ],
    )


class SamplePolicyOut(BaseModel):
    policy_id: uuid.UUID
    plan_id: str
    message: str


@router.post("/dev/sample-policy", status_code=status.HTTP_201_CREATED)
async def create_sample_policy(
    session: SessionDep, user: CurrentUser
) -> SamplePolicyOut:
    """給開發用：替目前登入的人建立一張範例保單（富邦進階型），並載入範例事件類型與待辦範本。

    5、6、7 號 agent 的負責人沒有真實保單可以上傳時，用這個就能走完事件流程（ADR-0015）。
    範例事件類型與待辦範本已存在就不重複載入；條款庫還沒載入（make seed）時回 409。
    """
    if (await session.exec(select(Insurance.id).limit(1))).first() is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "條款庫是空的，請先 make seed")
    await seed_sample_catalog(session)
    policy = Policy(
        user_id=user.id,
        display_name="範例保單（開發用）",
        plan_id="fubon_advanced",
        sum_insured=6_000_000,
    )
    session.add(policy)
    await session.commit()
    return SamplePolicyOut(
        policy_id=policy.id,
        plan_id=policy.plan_id,
        message="已建立範例保單，並載入事件類型與待辦範本（與 make seed 相同）",
    )
