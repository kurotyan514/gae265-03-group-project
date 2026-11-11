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


async def test_不再有任何類型自動加存摺_班機延誤只有兩份文件(
    session: AsyncSession,
) -> None:
    # Excel「事故理賠文件」沒有存摺；列成待辦會讓旅客只能勾「未附文件」，送件信寫「另行提供」（#194）
    await load_incident_catalog(session)

    assert await codes_of(session, "flight_delay") == ["D01", "D02"]
    for code in ("flight_cancel", "baggage_delay", "medical", "trip_cancel"):
        assert "D11" not in await codes_of(session, code)


async def test_醫療類列受益人身分證明_其他類型不列(session: AsyncSession) -> None:
    await load_incident_catalog(session)

    assert "D24" in await codes_of(session, "medical")
    for code in ("flight_delay", "flight_cancel", "baggage_delay", "baggage_loss"):
        assert "D24" not in await codes_of(session, code)
    for code in ("document_loss", "card_fraud", "trip_cancel"):
        assert "D24" not in await codes_of(session, code)


async def test_行李延誤不列購買必需品的收據(session: AsyncSession) -> None:
    await load_incident_catalog(session)

    assert await codes_of(session, "baggage_delay") == ["D06"]


async def test_證件遺失的_D17_改成重新申辦證明(session: AsyncSession) -> None:
    await load_incident_catalog(session)

    titles = (
        await session.exec(
            select(TodoTemplate.title).where(TodoTemplate.document_code == "D17")
        )
    ).all()
    assert titles == ["取得重新申辦旅行文件的證明（例如新護照或入國證明書）"]


HUANAN = "如果你的保單是華南產物，請另外附上損失清單及費用支出單據"


def test_定額型四類提醒華南要另附損失清單與費用單據() -> None:
    from app.domain.incident.catalog import type_notices

    for code in ("flight_delay", "baggage_delay", "baggage_loss", "document_loss"):
        assert HUANAN in [text for _, text in type_notices(code)], code
    for code in ("medical", "flight_cancel", "trip_cancel"):
        assert HUANAN not in [text for _, text in type_notices(code)], code


def test_醫療類提醒匯款時可能要存摺封面() -> None:
    from app.domain.incident.catalog import type_notices

    texts = [text for _, text in type_notices("medical")]
    assert "保險公司匯款時可能會跟你要存摺封面，可先準備" in texts


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


async def test_重跑載入會清掉一般事故類型的舊範本_事件一建立待辦是空的(
    session: AsyncSession,
) -> None:
    """#157：舊的開發資料庫留著 11/2 範例資料的「取得事故證明」「填寫理賠申請書」（沒有文件代碼），
    建立事件時會被複製成待辦，和 D10 重複，6 號辨識理賠申請書就對到好幾項待辦。
    資料檔沒有給一般事故類型（other）任何範本，重跑載入就該清乾淨。"""
    await load_incident_catalog(session)
    other = (
        await session.exec(select(IncidentType).where(IncidentType.code == "other"))
    ).one()
    for title in ("取得事故證明", "填寫理賠申請書"):
        session.add(
            TodoTemplate(
                incident_type_id=other.id,
                phase="after_return",
                title=title,
                sort_order=0,
            )
        )
    await session.commit()

    await load_incident_catalog(session)

    left = (
        await session.exec(
            select(TodoTemplate.title).where(TodoTemplate.incident_type_id == other.id)
        )
    ).all()
    assert left == []


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
