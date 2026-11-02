import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlmodel import col, select

from app.api.deps import CurrentUser, SessionDep
from app.domain.plans import Plan, get_plan, load_plans
from app.models import Conversation, ConversationInsurance, Insurance

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
