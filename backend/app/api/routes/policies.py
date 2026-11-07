"""保單上傳（ADR-0013）：收 PDF、抽文字，與條款庫的險種與方案比對；比對到才建立保單。

原檔、原文與原檔名都不保存。使用者再從保單選險種詢問，或以該對話建立理賠待辦清單。
"""

import asyncio
import uuid
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field, model_validator
from sqlmodel import col, select

from app.api.deps import CurrentUser, SessionDep
from app.api.routes.plans import ConversationOut
from app.core.config import settings
from app.domain.plans import UPLOAD_ONLY_MESSAGE, Plan, get_plan, load_plans
from app.models import (
    Conversation,
    ConversationInsurance,
    Insurance,
    PlanPremium,
    Policy,
    PolicyAddon,
)
from app.policy.code_map import load_current_code_map
from app.policy.extract import ExtractionError, PdfTextExtractor
from app.policy.matching import CatalogInsurance, match_insurances, match_plan
from app.policy.table import (
    TAIPEI,
    CodeTarget,
    match_plan_by_codes,
    parse_policy_facts,
)

router = APIRouter(tags=["policies"])

PDF_MIME = "application/pdf"
NO_MATCH_MESSAGE = (
    "條款庫裡沒有這份保單的商品方案，無法解析；請確認保單是否為本系統收錄的方案"
)


class PolicyInsuranceOut(BaseModel):
    code: str
    name: str


class PolicyAddonOut(BaseModel):
    code: str
    name: str
    section: str | None


class PolicyOut(BaseModel):
    id: uuid.UUID
    display_name: str
    plan_id: str
    plan_name: str
    company: str = Field(description="保險公司，由方案帶出（ADR-0019，不另存）")
    sum_insured: int | None
    destination: str | None = Field(description="目的地；上傳時由保單的旅遊國家帶入")
    start_date: date | None
    end_date: date | None
    start_at: datetime | None = Field(
        description="保障起的完整時間點（台北時間）；手選保單與保單沒印時分時是 null"
    )
    end_at: datetime | None = Field(description="保障迄的完整時間點，同 start_at")
    insurances: list[PolicyInsuranceOut]
    addons: list[PolicyAddonOut]
    created_at: datetime


class PolicyUploadOut(PolicyOut):
    """上傳保單的回應：多了只在這次出現、不存資料庫的欄位，給確認畫面顯示。"""

    product_name: str | None = Field(description="保單上印的商品名稱")
    riders: list[str] = Field(description="保單上的適用附加條款名稱")
    auto_filled: list[str] = Field(
        description="由保單讀到的欄位：company、plan、sum_insured、destination、period"
    )


async def _plan_insurances(session: SessionDep, plan: Plan | None) -> list[Insurance]:
    if plan is None:
        return []
    rows = (
        await session.exec(
            select(Insurance).where(col(Insurance.code).in_(plan.insurance_codes))
        )
    ).all()
    by_code = {i.code: i for i in rows}
    return [by_code[c] for c in plan.insurance_codes if c in by_code]


async def _addons(
    session: SessionDep, policy: Policy
) -> list[tuple[Insurance, str | None]]:
    rows = (
        await session.exec(
            select(Insurance, PolicyAddon.section)
            .join(PolicyAddon, col(PolicyAddon.insurance_id) == col(Insurance.id))
            .where(PolicyAddon.policy_id == policy.id)
            .order_by(col(Insurance.code), col(PolicyAddon.section))
        )
    ).all()
    return [(i, section) for i, section in rows]


def _taipei(value: datetime | None) -> datetime | None:
    """資料庫回來的是 UTC；對外一律用台北時間，上傳與查詢的回應才一致。"""
    return value.astimezone(TAIPEI) if value else None


async def _policy_out(session: SessionDep, policy: Policy) -> PolicyOut:
    plan = get_plan(policy.plan_id)
    insurances = await _plan_insurances(session, plan)
    addons = await _addons(session, policy)
    return PolicyOut(
        id=policy.id,
        display_name=policy.display_name,
        plan_id=policy.plan_id,
        plan_name=plan.name if plan else policy.plan_id,
        company=plan.company if plan else "",
        sum_insured=policy.sum_insured,
        destination=policy.destination,
        start_date=policy.start_date,
        end_date=policy.end_date,
        start_at=_taipei(policy.start_at),
        end_at=_taipei(policy.end_at),
        insurances=[PolicyInsuranceOut(code=i.code, name=i.name) for i in insurances],
        addons=[
            PolicyAddonOut(code=i.code, name=i.name, section=section)
            for i, section in addons
        ],
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
) -> PolicyUploadOut:
    """上傳保單 PDF，與條款庫比對方案。比對不到方案回 422，不留下任何資料。

    先用「承保內容」表印的險種代碼對照（目前支援富邦）；表上沒有認得的代碼時，退回用商品全名比對。
    """
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

    text = "\n".join(p.text for p in pages)
    facts = parse_policy_facts(text)
    plans = load_plans()
    by_code = match_plan_by_codes(
        facts.codes, plans, await load_current_code_map(session)
    )
    plan: Plan | None
    addon_targets: tuple[CodeTarget, ...]
    if by_code is not None:
        plan, addon_targets = by_code.plan, by_code.addons
    else:
        catalog = [
            CatalogInsurance(i.id, i.code, i.name)
            for i in (await session.exec(select(Insurance))).all()
        ]
        matched = match_insurances(text, catalog)
        plan, addon_targets = match_plan([i.code for i in matched], plans), ()
    if plan is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, NO_MATCH_MESSAGE)

    policy = Policy(
        user_id=user.id,
        # 不用原檔名（可能含姓名）
        display_name=f"{plan.name} {datetime.now(UTC):%Y-%m-%d %H:%M}",
        plan_id=plan.id,
        sum_insured=facts.sum_insured,
        destination=facts.destination,
        start_date=facts.start_date,
        end_date=facts.end_date,
        start_at=facts.start_at,
        end_at=facts.end_at,
    )
    session.add(policy)
    await session.flush()
    if addon_targets:
        by_insurance = {
            i.code: i
            for i in (
                await session.exec(
                    select(Insurance).where(
                        col(Insurance.code).in_({t.insurance for t in addon_targets})
                    )
                )
            ).all()
        }
        session.add_all(
            PolicyAddon(
                policy_id=policy.id,
                insurance_id=by_insurance[t.insurance].id,
                section=t.section,
            )
            for t in dict.fromkeys(addon_targets)
            if t.insurance in by_insurance
        )
    await session.commit()
    auto_filled = ["company", "plan"]  # 方案比對到才會建立，所以一定有
    if facts.sum_insured is not None:
        auto_filled.append("sum_insured")
    if facts.destination:
        auto_filled.append("destination")
    if facts.start_date and facts.end_date:
        auto_filled.append("period")
    return PolicyUploadOut(
        **(await _policy_out(session, policy)).model_dump(),
        product_name=facts.product_name,
        riders=list(facts.riders),
        auto_filled=auto_filled,
    )


class ManualPolicyIn(BaseModel):
    plan_id: str
    sum_insured: int
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def _period_in_order(self) -> ManualPolicyIn:
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("保險期間的結束日不能早於開始日")
        return self


@router.post("/policies/manual", status_code=status.HTTP_201_CREATED)
async def create_policy_manual(
    session: SessionDep, user: CurrentUser, body: ManualPolicyIn
) -> PolicyOut:
    """使用者自行選擇方案與保額建立保單（沒有 PDF，所以沒有加購，內容未經保單驗證）。

    保額必須是該方案有資料的保額（ADR-0018），方案不存在或保額不在範圍內回 422，不留下任何資料。
    """
    plan = get_plan(body.plan_id)
    if plan is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"找不到方案「{body.plan_id}」"
        )
    if plan.upload_only:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, UPLOAD_ONLY_MESSAGE)
    offered = (
        await session.exec(
            select(PlanPremium.id)
            .where(
                PlanPremium.plan_code == plan.id,
                PlanPremium.sum_insured == body.sum_insured,
            )
            .limit(1)
        )
    ).first()
    if offered is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"方案「{plan.name}」沒有身故保額 {body.sum_insured} 元",
        )
    policy = Policy(
        user_id=user.id,
        display_name=f"{plan.name} {datetime.now(UTC):%Y-%m-%d %H:%M}",
        plan_id=plan.id,
        sum_insured=body.sum_insured,
        start_date=body.start_date,
        end_date=body.end_date,
    )
    session.add(policy)
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
    """選這份保單發問：建立對話，險種是方案的險種加上加購的。理賠待辦清單也綁在這個對話上。"""
    policy = await _own_policy(session, user, policy_id)
    insurances = await _plan_insurances(session, get_plan(policy.plan_id))
    known = {i.id for i in insurances}
    insurances += [i for i, _ in await _addons(session, policy) if i.id not in known]
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
