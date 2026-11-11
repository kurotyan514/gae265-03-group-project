"""`GET /incidents` 依「最後操作時間」排序（#208）。

最後操作時間 = 事件本身與它的待辦、文件、對話訊息裡最新的一筆時間：
傳訊息、上傳文件、勾待辦都寫在別的表，不會動到事件那一列的 updated_at，所以要一起算。
"""

from datetime import UTC, datetime, timedelta

import pytest
from app.models import (
    Conversation,
    Incident,
    IncidentDocument,
    IncidentTodo,
    Message,
    Policy,
)
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

pytestmark = pytest.mark.usefixtures("user")

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


def later(minutes: int) -> datetime:
    return NOW + timedelta(minutes=minutes)


async def three_incidents(session: AsyncSession, policy: Policy) -> list[Incident]:
    """建立與更新時間都是 0、10、20 分：沒有任何後續操作時，B 在最前面、A 在最後。"""
    made = []
    for n, title in enumerate(["A", "B", "C"]):
        incident = Incident(
            policy_id=policy.id,
            title=title,
            description="d",
            created_at=later(n * 10),
            updated_at=later(n * 10),
        )
        session.add(incident)
        made.append(incident)
    await session.commit()
    return made


async def listing(client: AsyncClient) -> list[dict]:
    response = await client.get("/incidents")
    assert response.status_code == 200, response.text
    return response.json()


async def test_without_any_activity_it_is_the_creation_order(
    client: AsyncClient, session: AsyncSession, policy: Policy
) -> None:
    await three_incidents(session, policy)

    rows = await listing(client)

    assert [r["title"] for r in rows] == ["C", "B", "A"]
    # 沒有後續操作時，最後操作時間就是事件自己的更新時間
    assert datetime.fromisoformat(rows[2]["last_activity_at"]) == later(0)


async def test_a_new_message_moves_an_older_incident_to_the_top(
    client: AsyncClient, session: AsyncSession, policy: Policy
) -> None:
    a, _, _ = await three_incidents(session, policy)
    conversation = Conversation(
        kind="incident_qa", incident_id=a.id, user_id=policy.user_id
    )
    session.add(conversation)
    await session.flush()
    session.add(
        Message(
            conversation_id=conversation.id,
            seq=1,
            role="user",
            content="還有一件事",
            created_at=later(60),
        )
    )
    await session.commit()

    rows = await listing(client)

    assert [r["title"] for r in rows] == ["A", "C", "B"]
    assert datetime.fromisoformat(rows[0]["last_activity_at"]) == later(60)


async def test_a_todo_change_moves_an_older_incident_to_the_top(
    client: AsyncClient, session: AsyncSession, policy: Policy
) -> None:
    a, _, _ = await three_incidents(session, policy)
    session.add(
        IncidentTodo(
            incident_id=a.id,
            phase="on_site",
            title="取得證明",
            updated_at=later(45),
        )
    )
    await session.commit()

    rows = await listing(client)

    assert [r["title"] for r in rows] == ["A", "C", "B"]
    assert datetime.fromisoformat(rows[0]["last_activity_at"]) == later(45)


async def test_a_document_upload_moves_an_older_incident_to_the_top(
    client: AsyncClient, session: AsyncSession, policy: Policy
) -> None:
    _, b, _ = await three_incidents(session, policy)
    session.add(
        IncidentDocument(
            incident_id=b.id,
            file_name="證明.pdf",
            storage_path="drive-file-1",
            content_type="application/pdf",
            size_bytes=10,
            updated_at=later(90),
        )
    )
    await session.commit()

    rows = await listing(client)

    assert [r["title"] for r in rows] == ["B", "C", "A"]


async def test_activity_in_another_incident_does_not_leak(
    client: AsyncClient, session: AsyncSession, policy: Policy
) -> None:
    a, b, _ = await three_incidents(session, policy)
    session.add(
        IncidentTodo(incident_id=b.id, phase="on_site", title="x", updated_at=later(30))
    )
    await session.commit()

    rows = {r["title"]: r for r in await listing(client)}

    # B 的待辦只影響 B；A 的最後操作時間仍是自己的 0 分
    assert datetime.fromisoformat(rows["B"]["last_activity_at"]) == later(30)
    assert datetime.fromisoformat(rows["A"]["last_activity_at"]) == later(0)
    assert a.id != b.id


async def test_ties_are_broken_by_id_so_the_order_is_stable(
    client: AsyncClient, session: AsyncSession, policy: Policy
) -> None:
    for title in ["X", "Y"]:
        session.add(
            Incident(
                policy_id=policy.id,
                title=title,
                description="d",
                created_at=NOW,
                updated_at=NOW,
            )
        )
    await session.commit()

    first = [r["title"] for r in await listing(client)]
    second = [r["title"] for r in await listing(client)]

    assert first == second
