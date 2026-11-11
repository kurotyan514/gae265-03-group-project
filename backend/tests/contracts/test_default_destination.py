"""開事件沒帶目的地時，用保單的目的地（#202，規格 #184）。

旅客上傳保單時目的地已經讀進保單；開事件再問一次是多餘的。
有帶就以帶的為準，保單也沒有就維持空的。
"""

import pytest
from app.models import Incident, Policy
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

pytestmark = pytest.mark.usefixtures("user")


async def open_incident(
    client: AsyncClient, session: AsyncSession, policy: Policy, **body: object
) -> Incident:
    response = await client.post(
        f"/policies/{policy.id}/incidents", json={"description": "班機延誤了", **body}
    )
    assert response.status_code == 201, response.text
    incident = await session.get(Incident, response.json()["incident"]["incident_id"])
    assert incident is not None
    return incident


async def test_uses_the_policy_destination_when_none_is_given(
    client: AsyncClient, session: AsyncSession, policy: Policy
) -> None:
    policy.destination = "日本"
    session.add(policy)
    await session.commit()

    incident = await open_incident(client, session, policy)

    assert incident.destination == "日本"


@pytest.mark.parametrize("empty", [None, "", "  "])
async def test_blank_destination_counts_as_not_given(
    client: AsyncClient, session: AsyncSession, policy: Policy, empty: str | None
) -> None:
    policy.destination = "日本"
    session.add(policy)
    await session.commit()

    incident = await open_incident(client, session, policy, destination=empty)

    assert incident.destination == "日本"


async def test_a_given_destination_wins_over_the_policy(
    client: AsyncClient, session: AsyncSession, policy: Policy
) -> None:
    policy.destination = "日本"
    session.add(policy)
    await session.commit()

    incident = await open_incident(client, session, policy, destination="韓國")

    assert incident.destination == "韓國"


async def test_stays_empty_when_the_policy_has_no_destination(
    client: AsyncClient, session: AsyncSession, policy: Policy
) -> None:
    assert policy.destination is None

    incident = await open_incident(client, session, policy)

    assert incident.destination is None
