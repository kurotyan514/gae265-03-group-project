"""擁有者檢查與 agent 註冊。"""

import uuid

import pytest
from app.agents import registry
from app.contracts.fakes import FakeIncidentAgent
from app.core.config import settings
from app.models import Incident, Policy, User
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

pytestmark = pytest.mark.usefixtures("user")


@pytest.mark.usefixtures("catalog_loaded")
async def test_other_users_incident_is_404_everywhere(
    client: AsyncClient, session: AsyncSession
) -> None:
    other = User(email="other@example.com")
    session.add(other)
    await session.commit()
    policy = Policy(user_id=other.id, display_name="別人的", plan_id="fubon_advanced")
    session.add(policy)
    await session.commit()
    incident = Incident(policy_id=policy.id, title="t", description="d")
    session.add(incident)
    await session.commit()
    i = incident.id

    calls = [
        client.get(f"/incidents/{i}"),
        client.post(f"/incidents/{i}/messages", json={"content": "x"}),
        client.patch(f"/incidents/{i}/todos/{uuid.uuid4()}", json={"is_done": True}),
        client.post(
            f"/incidents/{i}/documents",
            files={"file": ("a.pdf", b"x", "application/pdf")},
        ),
        client.get(f"/incidents/{i}/package"),
        client.post(f"/incidents/{i}/submission", json={"recipient": "a@b.c"}),
        client.post(f"/policies/{policy.id}/incidents", json={"description": "x"}),
    ]
    for call in calls:
        assert (await call).status_code == 404
    assert (await client.get("/incidents")).json() == []


async def test_unknown_implementation_name_fails_with_the_available_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AGENT_5_IMPL", "nope")
    with pytest.raises(RuntimeError, match="fake"):
        registry.get_incident_agent()


async def test_registered_implementation_can_be_selected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(registry._INCIDENT, "mine", FakeIncidentAgent)
    monkeypatch.setattr(settings, "AGENT_5_IMPL", "mine")
    assert isinstance(registry.get_incident_agent(), FakeIncidentAgent)
