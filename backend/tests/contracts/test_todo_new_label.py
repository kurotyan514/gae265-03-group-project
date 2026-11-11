"""待辦的「新增」標籤（規格 4.5 R5：新適用的待辦加入並標「新增」，勾選後標籤消失；#232）。"""

import uuid

import pytest
from app.contracts import IncidentReply, TodoApplicability
from app.contracts.fakes import FakeIncidentAgent
from app.models import Policy
from httpx import AsyncClient

from tests.contracts.test_v2 import start, talk

pytestmark = pytest.mark.usefixtures("user")


class MarkingAgent(FakeIncidentAgent):
    """回覆時帶上指定的適用註記。"""

    def __init__(self, todo_id: str, applicable: bool) -> None:
        self.mark = TodoApplicability(todo_id=uuid.UUID(todo_id), applicable=applicable)

    async def reply(self, ctx, user_message, input_mode, services):  # type: ignore[override]
        return IncidentReply(message="好的", todo_applicability=[self.mark])


async def mark(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    incident_id: str,
    todo_id: str,
    applicable: bool,
) -> dict:
    monkeypatch.setattr(
        "app.api.routes.incidents.get_incident_agent",
        lambda: MarkingAgent(todo_id, applicable),
    )
    response = await client.post(
        f"/incidents/{incident_id}/messages", json={"content": "更正一下"}
    )
    assert response.status_code == 200, response.text
    return response.json()["incident"]


def by_code(state: dict, code: str) -> dict:
    return next(t for t in state["todos"] if t["document_code"] == code)


async def test_第一次下結論產生的待辦不標新增(
    client: AsyncClient, policy: Policy
) -> None:
    incident_id = await start(client, policy)
    state = await talk(client, incident_id)

    assert state["todos"] and not any(t["is_new"] for t in state["todos"])


async def test_改回適用的待辦標新增_勾選後消失(
    client: AsyncClient, policy: Policy, monkeypatch: pytest.MonkeyPatch
) -> None:
    incident_id = await start(client, policy)
    d01 = by_code(await talk(client, incident_id), "D01")

    off = await mark(client, monkeypatch, incident_id, d01["id"], False)
    assert by_code(off, "D01")["is_new"] is False
    on = await mark(client, monkeypatch, incident_id, d01["id"], True)
    assert by_code(on, "D01")["is_new"] is True

    ticked = await client.patch(
        f"/incidents/{incident_id}/todos/{d01['id']}", json={"is_done": True}
    )
    assert ticked.status_code == 200, ticked.text
    state = (await client.get(f"/incidents/{incident_id}")).json()
    assert by_code(state, "D01")["is_new"] is False
