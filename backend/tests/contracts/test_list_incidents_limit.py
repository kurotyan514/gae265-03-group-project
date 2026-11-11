"""`GET /incidents` 的 `limit`（#207）：首頁「我的理賠」只要最近 3 筆，不帶就回全部。"""

from datetime import UTC, datetime, timedelta

import pytest
from app.models import Incident, Policy, User
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

pytestmark = pytest.mark.usefixtures("user")

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


async def add_incidents(
    session: AsyncSession, policy: Policy, count: int, *, prefix: str = "事件"
) -> None:
    """建立與更新時間依序遞增（沒有後續操作）：最後建立的在最前面。"""
    for n in range(count):
        session.add(
            Incident(
                policy_id=policy.id,
                title=f"{prefix}{n}",
                description="d",
                created_at=NOW + timedelta(minutes=n),
                updated_at=NOW + timedelta(minutes=n),
            )
        )
    await session.commit()


async def titles(client: AsyncClient, limit: int | None = None) -> list[str]:
    params = {} if limit is None else {"limit": limit}
    response = await client.get("/incidents", params=params)
    assert response.status_code == 200, response.text
    return [row["title"] for row in response.json()]


async def test_without_limit_returns_everything_newest_first(
    client: AsyncClient, session: AsyncSession, policy: Policy
) -> None:
    await add_incidents(session, policy, 5)

    assert await titles(client) == ["事件4", "事件3", "事件2", "事件1", "事件0"]


async def test_limit_keeps_only_the_newest(
    client: AsyncClient, session: AsyncSession, policy: Policy
) -> None:
    await add_incidents(session, policy, 5)

    assert await titles(client, limit=3) == ["事件4", "事件3", "事件2"]


async def test_limit_larger_than_the_count_returns_all(
    client: AsyncClient, session: AsyncSession, policy: Policy
) -> None:
    await add_incidents(session, policy, 2)

    assert await titles(client, limit=100) == ["事件1", "事件0"]


@pytest.mark.parametrize("limit", [0, -1, 101])
async def test_limit_out_of_range_is_rejected(client: AsyncClient, limit: int) -> None:
    response = await client.get("/incidents", params={"limit": limit})

    assert response.status_code == 422


async def test_only_my_incidents_are_listed_even_with_limit(
    client: AsyncClient, session: AsyncSession, policy: Policy
) -> None:
    other = User(email="other-list@example.com")
    session.add(other)
    await session.commit()
    theirs = Policy(user_id=other.id, display_name="別人的", plan_id="fubon_advanced")
    session.add(theirs)
    await session.commit()
    await add_incidents(session, policy, 2)
    # 別人的事件建立得更晚，但不能出現在我的清單
    session.add(
        Incident(
            policy_id=theirs.id,
            title="別人的事件",
            description="d",
            created_at=NOW + timedelta(hours=1),
            updated_at=NOW + timedelta(hours=1),
        )
    )
    await session.commit()

    assert await titles(client, limit=3) == ["事件1", "事件0"]
