"""故意違反契約的 agent：平台必須回 502，而且一筆都不寫。"""

import uuid

import pytest
from app.contracts import (
    Citation,
    ClauseUpdate,
    IncidentReply,
    Recognition,
    TodoProposal,
)
from app.contracts.fakes import FakeDocumentRecognizer, FakeIncidentAgent
from app.models import (
    IncidentDocument,
    IncidentFact,
    IncidentTodo,
    Message,
    MessageCitation,
    Policy,
)
from httpx import AsyncClient
from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

pytestmark = pytest.mark.usefixtures("user")


async def count(session: AsyncSession, model: type) -> int:
    return (await session.exec(select(func.count()).select_from(model))).one()


class BadAgent(FakeIncidentAgent):
    def __init__(self, bad: IncidentReply) -> None:
        self.bad = bad

    async def reply(self, ctx, user_message, input_mode, services):  # type: ignore[override]
        return self.bad


BAD_REPLIES = {
    "未知的事件類型": IncidentReply(message="x", incident_type_code="no-such-type"),
    "保單沒涵蓋的保障": IncidentReply(
        message="x", clauses=[ClauseUpdate(insurance_code="CHUBB05", section=None)]
    ),
    "險種不在保單內的出處": IncidentReply(
        message="x", citations=[Citation(insurance_code="CHUBB05", article_no=1)]
    ),
    "不存在的條文": IncidentReply(
        message="x", citations=[Citation(insurance_code="FUBON01", article_no=999)]
    ),
    "不屬於該類型的待辦範本": IncidentReply(
        message="x",
        incident_type_code="flight_delay",
        todos=[TodoProposal(phase="on_site", title="x", template_id=uuid.uuid4())],
    ),
}


@pytest.mark.parametrize("name", BAD_REPLIES)
async def test_bad_incident_reply_is_rejected_and_nothing_is_written(
    name: str,
    client: AsyncClient,
    session: AsyncSession,
    policy: Policy,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = await client.post(
        f"/policies/{policy.id}/incidents", json={"description": "出事了"}
    )
    incident_id = created.json()["incident"]["incident_id"]
    before = [
        await count(session, m)
        for m in (Message, IncidentFact, IncidentTodo, MessageCitation)
    ]

    monkeypatch.setattr(
        "app.api.routes.incidents.get_incident_agent",
        lambda: BadAgent(BAD_REPLIES[name]),
    )
    response = await client.post(
        f"/incidents/{incident_id}/messages", json={"content": "再說一句"}
    )

    assert response.status_code == 502, (name, response.text)
    assert "不符合契約" in response.json()["detail"]
    assert "再說一句" not in response.text  # 訊息不含使用者內容
    after = [
        await count(session, m)
        for m in (Message, IncidentFact, IncidentTodo, MessageCitation)
    ]
    assert after == before, name


class BadRecognizer(FakeDocumentRecognizer):
    def __init__(self, result: Recognition) -> None:
        self.result = result

    async def recognize(self, ctx, file, user, google):  # type: ignore[override]
        return self.result


BAD_RECOGNITIONS = {
    "待辦屬於別的事件": Recognition(
        status="recognized",
        matched_todo_id=uuid.uuid4(),
        todo_complete=True,
        storage_path="x",
    ),
    "辨識通過卻沒存雲端": Recognition(status="recognized", storage_path=None),
    "沒辨識通過卻勾待辦": Recognition(status="needs_review", todo_complete=True),
    "不合格卻沒寫缺什麼": Recognition(status="incomplete"),
    "不合格卻保留了檔案": Recognition(
        status="incomplete", reason="缺少最後一頁", storage_path="x"
    ),
    "失敗卻保留了檔案": Recognition(status="failed", storage_path="x"),
}


@pytest.mark.parametrize("name", BAD_RECOGNITIONS)
async def test_bad_recognition_is_rejected_and_nothing_is_written(
    name: str,
    client: AsyncClient,
    session: AsyncSession,
    policy: Policy,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = await client.post(
        f"/policies/{policy.id}/incidents", json={"description": "出事了"}
    )
    incident_id = created.json()["incident"]["incident_id"]

    monkeypatch.setattr(
        "app.api.routes.incidents.get_document_recognizer",
        lambda: BadRecognizer(BAD_RECOGNITIONS[name]),
    )
    response = await client.post(
        f"/incidents/{incident_id}/documents",
        files={"file": ("a.pdf", b"%PDF-1.4", "application/pdf")},
    )

    assert response.status_code == 502, (name, response.text)
    assert await count(session, IncidentDocument) == 0
    assert not any(t.is_done for t in (await session.exec(select(IncidentTodo))).all())
