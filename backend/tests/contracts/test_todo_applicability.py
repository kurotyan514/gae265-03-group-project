"""5 號註記待辦適不適用（契約 v2.4.0，#232）。

只是 1/0 註記：不改待辦原本是待辦還是完成，也不動已上傳的文件；不適用的待辦在完成檢查、
送件、辨識、打包都當作不存在，改回適用就恢復。
"""

import uuid

import pytest
from app.contracts import IncidentReply, TodoApplicability
from app.contracts.fakes import FakeIncidentAgent
from app.models import Policy
from httpx import AsyncClient

from tests.contracts.test_v2 import start, talk

pytestmark = pytest.mark.usefixtures("user")


class ApplicabilityAgent(FakeIncidentAgent):
    """每次回覆都帶上指定的適用註記。"""

    def __init__(self, marks: list[tuple[str, bool]]) -> None:
        self.marks = [
            TodoApplicability(todo_id=uuid.UUID(i), applicable=a) for i, a in marks
        ]

    async def reply(self, ctx, user_message, input_mode, services):  # type: ignore[override]
        return IncidentReply(message="好的", todo_applicability=self.marks)


def mark(monkeypatch: pytest.MonkeyPatch, *marks: tuple[str, bool]) -> None:
    monkeypatch.setattr(
        "app.api.routes.incidents.get_incident_agent",
        lambda: ApplicabilityAgent(list(marks)),
    )


async def say(client: AsyncClient, incident_id: str) -> dict:
    response = await client.post(
        f"/incidents/{incident_id}/messages", json={"content": "更正一下"}
    )
    assert response.status_code == 200, response.text
    return response.json()["incident"]


def by_code(state: dict, code: str) -> dict:
    return next(t for t in state["todos"] if t["document_code"] == code)


async def test_預設全部適用(client: AsyncClient, policy: Policy) -> None:
    incident_id = await start(client, policy)
    state = await talk(client, incident_id)
    assert state["todos"] and all(t["applicable"] for t in state["todos"])


async def test_註記不適用_不刪不改狀態_改回適用就恢復(
    client: AsyncClient, policy: Policy, monkeypatch: pytest.MonkeyPatch
) -> None:
    incident_id = await start(client, policy)
    state = await talk(client, incident_id)
    d01 = by_code(state, "D01")
    # 先勾完成：註記不適用不能把它變回待辦
    done = await client.patch(
        f"/incidents/{incident_id}/todos/{d01['id']}", json={"is_done": True}
    )
    assert done.status_code == 200, done.text

    mark(monkeypatch, (d01["id"], False))
    after = await say(client, incident_id)
    assert len(after["todos"]) == len(state["todos"])  # 沒有刪除
    assert by_code(after, "D01")["applicable"] is False
    assert by_code(after, "D01")["status"] == "done"  # 狀態原封不動
    assert by_code(after, "D02")["applicable"] is True  # 沒列到的不動

    mark(monkeypatch, (d01["id"], True))
    back = await say(client, incident_id)
    assert by_code(back, "D01")["applicable"] is True
    assert by_code(back, "D01")["status"] == "done"


async def test_不適用的待辦不算在完成檢查裡_可以送件(
    client: AsyncClient, policy: Policy, monkeypatch: pytest.MonkeyPatch
) -> None:
    incident_id = await start(client, policy)
    state = await talk(client, incident_id)
    d01 = by_code(state, "D01")
    mark(monkeypatch, (d01["id"], False))
    await say(client, incident_id)

    cannot = await client.post(
        f"/incidents/{incident_id}/submission", json={"mode": "self"}
    )
    assert cannot.status_code == 409  # 其他待辦還沒完成

    for t in state["todos"]:
        if t["id"] == d01["id"]:
            continue
        ticked = await client.patch(
            f"/incidents/{incident_id}/todos/{t['id']}", json={"is_done": True}
        )
        assert ticked.status_code == 200, ticked.text

    submitted = await client.post(
        f"/incidents/{incident_id}/submission", json={"mode": "self"}
    )
    assert submitted.status_code == 201, submitted.text  # D01 還是待辦，但當作不存在


async def test_送件包不把不適用的待辦算成缺的(
    client: AsyncClient, policy: Policy, monkeypatch: pytest.MonkeyPatch
) -> None:
    incident_id = await start(client, policy)
    state = await talk(client, incident_id)
    d01 = by_code(state, "D01")
    before = (await client.get(f"/incidents/{incident_id}/package")).json()
    assert d01["id"] in before["missing_todo_ids"]

    mark(monkeypatch, (d01["id"], False))
    await say(client, incident_id)

    after = (await client.get(f"/incidents/{incident_id}/package")).json()
    assert d01["id"] not in after["missing_todo_ids"]


async def test_不適用的待辦不能勾選也不能上傳文件(
    client: AsyncClient, policy: Policy, monkeypatch: pytest.MonkeyPatch
) -> None:
    incident_id = await start(client, policy)
    d01 = by_code(await talk(client, incident_id), "D01")
    mark(monkeypatch, (d01["id"], False))
    await say(client, incident_id)

    ticked = await client.patch(
        f"/incidents/{incident_id}/todos/{d01['id']}", json={"is_done": True}
    )
    assert ticked.status_code == 409

    uploaded = await client.post(
        f"/incidents/{incident_id}/documents",
        files={"file": ("a證明.pdf", b"%PDF-1.4", "application/pdf")},
        data={"todo_id": d01["id"]},
    )
    assert uploaded.status_code == 409


async def test_已上傳的文件留著(
    client: AsyncClient, policy: Policy, monkeypatch: pytest.MonkeyPatch
) -> None:
    incident_id = await start(client, policy)
    d02 = by_code(await talk(client, incident_id), "D02")
    uploaded = await client.post(
        f"/incidents/{incident_id}/documents",
        files={"file": ("a證明.pdf", b"%PDF-1.4", "application/pdf")},
        data={"todo_id": d02["id"]},
    )
    assert uploaded.status_code == 201, uploaded.text
    document_id = uploaded.json()["id"]

    mark(monkeypatch, (d02["id"], False))
    after = await say(client, incident_id)

    assert by_code(after, "D02")["status"] == "done"  # 狀態不變
    assert any(d["id"] == document_id for d in after["documents"])  # 文件還在
    assert (
        next(d for d in after["documents"] if d["id"] == document_id)["todo_id"]
        == d02["id"]
    )


@pytest.mark.parametrize("which", ["shared", "unknown"])
async def test_只能註記這個事件自己的待辦(
    which: str, client: AsyncClient, policy: Policy, monkeypatch: pytest.MonkeyPatch
) -> None:
    incident_id = await start(client, policy)
    state = await talk(client, incident_id)
    bad = by_code(state, "D10")["id"] if which == "shared" else str(uuid.uuid4())
    mark(monkeypatch, (bad, False))

    response = await client.post(
        f"/incidents/{incident_id}/messages", json={"content": "更正"}
    )

    assert response.status_code == 502
    assert "不符合契約" in response.json()["detail"]
    after = (await client.get(f"/incidents/{incident_id}")).json()
    assert all(t["applicable"] for t in after["todos"])  # 一筆都沒寫
