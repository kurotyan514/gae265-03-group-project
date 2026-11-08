"""待辦依事件的答案決定要不要建立：todo_template.condition（incident_catalog.json）。"""

import pytest
from app.contracts import IncidentReply
from app.contracts.incident_agent import ClauseUpdate, FactUpdate
from app.domain.incident import service
from app.models import IncidentTodo, Insurance, Policy, User
from app.seed import load_incident_catalog
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession


async def todo_codes(
    session: AsyncSession, type_code: str, insurance: str, answers: dict[str, str]
) -> set[str]:
    """走一次「5 號回報類型、答案與可能適用」，回傳建出來的事件待辦文件代碼。"""
    await load_incident_catalog(session)
    user = User(email="todo@example.com")
    session.add_all([user, Insurance(code=insurance, name=insurance)])
    await session.flush()
    policy = Policy(
        user_id=user.id, display_name="進階型", plan_id="fubon_advanced", sum_insured=1
    )
    session.add(policy)
    await session.flush()
    incident = await service.create_incident(
        session, policy, description="事故", destination=None, title=None
    )
    await session.commit()

    ctx = await service.build_context(session, incident)
    await service.apply_reply(
        session,
        incident,
        ctx,
        IncidentReply(
            message="整理好了",
            incident_type_code=type_code,
            facts=[
                FactUpdate(fact_key=k, label=k, value=v) for k, v in answers.items()
            ],
            clauses=[
                ClauseUpdate(insurance_code=insurance, conclusion="applicable"),
            ],
        ),
    )
    await session.commit()
    rows = await session.exec(
        select(IncidentTodo.document_code).where(
            IncidentTodo.incident_id == incident.id
        )
    )
    return {c for c in rows if c}


@pytest.mark.parametrize(("hosp", "listed"), [("是", True), ("否", False)])
async def test_住院證明只在有住院時列出(
    session: AsyncSession, hosp: str, listed: bool
) -> None:
    codes = await todo_codes(session, "medical", "FUBON02", {"hosp": hosp})

    assert ("D15" in codes) is listed
    assert "D13" in codes  # 沒有條件的文件照常列出


THEFT = "被偷、被搶或被扒"
CHECKED_LOST = "託運行李被航空公司弄丟"


@pytest.mark.parametrize(
    ("cause", "listed", "absent"),
    [
        (THEFT, {"D16"}, {"D06", "D08"}),
        (CHECKED_LOST, {"D06", "D08"}, {"D16"}),
    ],
)
async def test_行李遺失依事故原因列不同文件(
    session: AsyncSession, cause: str, listed: set[str], absent: set[str]
) -> None:
    codes = await todo_codes(session, "baggage_loss", "FUBON03", {"cause": cause})

    assert listed <= codes
    assert not absent & codes


async def test_行李延誤的_PIR_不受行李遺失的條件影響(session: AsyncSession) -> None:
    codes = await todo_codes(session, "baggage_delay", "FUBON03", {})

    assert "D06" in codes


def test_行李遺失的條件和_5_號的選項文字一致() -> None:
    import json

    from app.agents.incident.judge import CHECKED_LOST as code_lost
    from app.agents.incident.judge import THEFT as code_theft
    from app.core.config import settings

    catalog = json.loads(
        (settings.CONFIG_DIR / "incident_catalog.json").read_text(encoding="utf-8")
    )
    baggage = next(t for t in catalog["types"] if t["code"] == "baggage_loss")
    values = {c["equals"] for c in baggage["document_conditions"].values()}

    assert values == {code_theft, code_lost}


async def test_待辦帶出文件條件給_5_號判斷(session: AsyncSession) -> None:
    """契約 2.5.0：5 號修正描述時用 condition 判斷哪些待辦不再適用。"""
    await load_incident_catalog(session)
    user = User(email="cond@example.com")
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
            facts=[FactUpdate(fact_key="cause", label="原因", value=CHECKED_LOST)],
            clauses=[ClauseUpdate(insurance_code="FUBON03", conclusion="applicable")],
        ),
    )
    await session.commit()

    ctx = await service.build_context(session, incident)

    pir = next(t for t in ctx.todos if t.document_code == "D06")
    assert pir.condition == {"field": "cause", "equals": CHECKED_LOST}
    assert ctx.policy.policy_id == policy.id
