"""5 號回報待辦改成不適用或恢復（契約 2.4.0，規格 4.5 R5，#232）。"""

import uuid

import pytest
from app.contracts import ContractViolation, IncidentReply
from app.contracts.incident_agent import ClauseUpdate, FactUpdate, TodoStatusUpdate
from app.domain.incident import service
from app.models import Incident, IncidentTodo, Insurance, Policy, User
from app.seed import load_incident_catalog
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession


async def lost_baggage(session: AsyncSession) -> Incident:
    """託運弄丟、可能適用的事件：建好 PIR、航空公司證明與理賠申請書。"""
    await load_incident_catalog(session)
    user = User(email="status@example.com")
    session.add_all([user, Insurance(code="FUBON03", name="FUBON03")])
    await session.flush()
    policy = Policy(
        user_id=user.id, display_name="進階型", plan_id="fubon_advanced", sum_insured=1
    )
    session.add(policy)
    await session.flush()
    incident = await service.create_incident(
        session, policy, description="行李不見", destination=None, title=None
    )
    ctx = await service.build_context(session, incident)
    await service.apply_reply(
        session,
        incident,
        ctx,
        IncidentReply(
            message="整理好了",
            incident_type_code="baggage_loss",
            facts=[
                FactUpdate(
                    fact_key="cause", label="原因", value="託運行李被航空公司弄丟"
                )
            ],
            clauses=[ClauseUpdate(insurance_code="FUBON03", conclusion="applicable")],
        ),
    )
    await session.commit()
    return incident


async def update(
    session: AsyncSession, incident: Incident, *updates: TodoStatusUpdate
) -> None:
    ctx = await service.build_context(session, incident)
    await service.apply_reply(
        session,
        incident,
        ctx,
        IncidentReply(message="更新", todo_updates=list(updates)),
    )
    await session.commit()


async def todo(session: AsyncSession, incident: Incident, code: str) -> IncidentTodo:
    return (
        await session.exec(
            select(IncidentTodo)
            .where(
                IncidentTodo.incident_id == incident.id,
                IncidentTodo.document_code == code,
            )
            .execution_options(populate_existing=True)
        )
    ).one()


async def test_5_號把待辦標成不適用_待辦保留(session: AsyncSession) -> None:
    incident = await lost_baggage(session)
    pir = await todo(session, incident, "D06")

    await update(
        session, incident, TodoStatusUpdate(todo_id=pir.id, status="not_applicable")
    )

    assert (await todo(session, incident, "D06")).status == "not_applicable"
    assert (await todo(session, incident, "D08")).status == "pending"


async def test_已完成的待辦也可以標不適用_恢復時回到已完成(
    session: AsyncSession,
) -> None:
    incident = await lost_baggage(session)
    pir = await todo(session, incident, "D06")
    pir.status, pir.done_by = "done", "user"
    session.add(pir)
    await session.commit()

    await update(
        session, incident, TodoStatusUpdate(todo_id=pir.id, status="not_applicable")
    )
    assert (await todo(session, incident, "D06")).status == "not_applicable"

    await update(session, incident, TodoStatusUpdate(todo_id=pir.id, status="pending"))
    assert (await todo(session, incident, "D06")).status == "done"


async def test_不是這個事件的待辦_違反契約(session: AsyncSession) -> None:
    incident = await lost_baggage(session)

    with pytest.raises(ContractViolation):
        await update(
            session,
            incident,
            TodoStatusUpdate(todo_id=uuid.uuid4(), status="not_applicable"),
        )


async def test_整個行程共用的理賠申請書不能標不適用(session: AsyncSession) -> None:
    incident = await lost_baggage(session)
    ctx = await service.build_context(session, incident)
    claim_form = next(t for t in ctx.todos if t.scope == "policy")

    with pytest.raises(ContractViolation):
        await update(
            session,
            incident,
            TodoStatusUpdate(todo_id=claim_form.id, status="not_applicable"),
        )


async def test_待辦帶出文件條件給_5_號判斷(session: AsyncSession) -> None:
    incident = await lost_baggage(session)

    ctx = await service.build_context(session, incident)

    pir = next(t for t in ctx.todos if t.document_code == "D06")
    assert pir.condition == {"field": "cause", "equals": "託運行李被航空公司弄丟"}
