"""契約 v2 的資料表變更：一項待辦可收多份文件、辨識狀態多一種 incomplete、兩個新旗標。"""

import pytest
from app.models import Incident, IncidentDocument, IncidentTodo, Policy, User
from sqlalchemy.exc import IntegrityError
from sqlmodel.ext.asyncio.session import AsyncSession


async def make_todo(session: AsyncSession) -> tuple[Incident, IncidentTodo]:
    user = User(email="v2@example.com")
    session.add(user)
    await session.flush()
    policy = Policy(
        user_id=user.id, display_name="進階型", plan_id="fubon_advanced", sum_insured=1
    )
    session.add(policy)
    await session.flush()
    incident = Incident(policy_id=policy.id, title="班機延誤", description="延誤")
    session.add(incident)
    await session.flush()
    todo = IncidentTodo(incident_id=incident.id, phase="on_site", title="機票及登機證")
    session.add(todo)
    await session.commit()
    return incident, todo


def document(
    incident: Incident, todo: IncidentTodo, name: str, status: str = "recognized"
) -> IncidentDocument:
    return IncidentDocument(
        incident_id=incident.id,
        incident_todo_id=todo.id,
        file_name=name,
        size_bytes=1,
        storage_path="drive-file-id",
        content_type="application/pdf",
        recognition_status=status,
    )


async def test_一項待辦可以收多份文件(session: AsyncSession) -> None:
    incident, todo = await make_todo(session)

    session.add_all(
        [document(incident, todo, "機票_1.pdf"), document(incident, todo, "機票_2.pdf")]
    )
    await session.commit()  # 以前這裡會因為 incident_todo_id 唯一而失敗


async def test_辨識狀態可以是_incomplete(session: AsyncSession) -> None:
    incident, todo = await make_todo(session)

    session.add(document(incident, todo, "缺頁.pdf", status="incomplete"))
    await session.commit()


async def test_不認得的辨識狀態仍然被擋下(session: AsyncSession) -> None:
    incident, todo = await make_todo(session)

    session.add(document(incident, todo, "x.pdf", status="whatever"))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_新旗標預設是_False(session: AsyncSession) -> None:
    incident, todo = await make_todo(session)
    doc = document(incident, todo, "a.pdf")
    session.add(doc)
    await session.commit()

    await session.refresh(todo)
    await session.refresh(doc)
    assert todo.without_document is False
    assert doc.confirmed_by_user is False
