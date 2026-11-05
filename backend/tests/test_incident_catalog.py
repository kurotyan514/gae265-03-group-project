"""事故類型與理賠文件規則（incident_catalog.json）載入後的內容。"""

from app.models import (
    Incident,
    IncidentTodo,
    IncidentType,
    Policy,
    TodoTemplate,
    User,
)
from app.seed import load_incident_catalog
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession


async def codes_of(session: AsyncSession, type_code: str) -> list[str]:
    rows = await session.exec(
        select(TodoTemplate.document_code)
        .join(IncidentType, IncidentType.id == TodoTemplate.incident_type_id)  # pyright: ignore[reportArgumentType]
        .where(IncidentType.code == type_code)
    )
    return sorted(c for c in rows if c)


async def test_班機延誤不列_D11_其他類型照常有(session: AsyncSession) -> None:
    await load_incident_catalog(session)

    assert await codes_of(session, "flight_delay") == ["D01", "D02"]
    # 其他類型仍然自動加上 D11（是否排除由文件規則維護者另外決定）
    for code in ("flight_cancel", "baggage_delay", "medical", "trip_cancel"):
        assert "D11" in await codes_of(session, code)


async def test_班機延誤與取消共用的延誤證明用新標題(session: AsyncSession) -> None:
    await load_incident_catalog(session)

    titles = (
        await session.exec(
            select(TodoTemplate.title).where(TodoTemplate.document_code == "D01")
        )
    ).all()
    assert titles and set(titles) == {"航空業者出具、載有班機延誤期間或取消的證明"}


async def test_重跑載入會清掉資料檔不再列的舊範本_已建立的待辦保留(
    session: AsyncSession,
) -> None:
    await load_incident_catalog(session)
    delay = (
        await session.exec(
            select(IncidentType).where(IncidentType.code == "flight_delay")
        )
    ).one()
    # 模擬舊的開發資料庫：班機延誤還有 D11 的範本，而且已經有事件用它建了待辦
    old = TodoTemplate(
        incident_type_id=delay.id,
        document_code="D11",
        phase="after_return",
        title="準備存摺封面與護照影本",
        sort_order=9,
    )
    user = User(email="old@example.com")
    session.add_all([old, user])
    await session.flush()
    policy = Policy(
        user_id=user.id, display_name="進階型", plan_id="fubon_advanced", sum_insured=1
    )
    session.add(policy)
    await session.flush()
    incident = Incident(policy_id=policy.id, title="班機延誤", description="延誤")
    session.add(incident)
    await session.flush()
    todo = IncidentTodo(
        incident_id=incident.id,
        todo_template_id=old.id,
        document_code="D11",
        phase="after_return",
        title="準備存摺封面與護照影本",
    )
    session.add(todo)
    await session.commit()
    todo_id = todo.id

    await load_incident_catalog(session)

    assert await codes_of(session, "flight_delay") == ["D01", "D02"]
    session.expire_all()
    kept = await session.get(IncidentTodo, todo_id)
    assert kept is not None and kept.todo_template_id is None


# ---- 重大注意事項（契約 v2）----


def test_重大注意事項依優先序取前四條_去掉重複() -> None:
    from app.domain.incident.catalog import compose_major_notices

    majors = [(3, "丙"), (1, "甲"), (2, "乙"), (4, "丁"), (5, "戊"), (1, "甲")]

    assert compose_major_notices(None, majors, None, None) == ["甲", "乙", "丙", "丁"]


def test_重大注意事項帶入保單的實際日期() -> None:
    from datetime import date

    from app.domain.incident.catalog import render_notice

    text = "保險期間 {start_date} 到 {end_date} 內發生的事故才賠"

    assert (
        render_notice(text, date(2026, 11, 1), date(2026, 11, 8))
        == "保險期間 2026/11/01 到 2026/11/08 內發生的事故才賠"
    )


def test_保單沒有日期時含日期的提醒不顯示_寧可不顯示也不顯示錯的() -> None:
    from datetime import date

    from app.domain.incident.catalog import compose_major_notices, render_notice

    assert render_notice("期間 {start_date}", None, date(2026, 11, 8)) is None
    assert compose_major_notices(
        None, [(1, "期間 {start_date}"), (2, "單據要保留正本")], None, None
    ) == ["單據要保留正本"]


def test_事故類型對應保障_章名含關鍵字才算_整份險種比對不到() -> None:
    from app.contracts.common import CoverageRef
    from app.domain.incident.catalog import matching_coverages

    coverages = [
        CoverageRef(insurance_code="A", section="第三章 班機延誤保險(定額給付)"),
        CoverageRef(insurance_code="A", section="第四章 行李延誤保險"),
        CoverageRef(insurance_code="B"),  # 整份險種沒有章名
    ]

    assert matching_coverages(["班機延誤"], coverages) == [coverages[0]]
