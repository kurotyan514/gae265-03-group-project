"""從保單到送件的整條流程（ADR-0015）。預設跑假實作；換成真實實作時用同一組測試驗證。"""

import uuid

import pytest
from app.models import (
    Conversation,
    Incident,
    IncidentClause,
    IncidentDocument,
    IncidentFact,
    IncidentTodo,
    Message,
    MessageCitation,
    Policy,
    PolicySubmission,
)
from httpx import AsyncClient
from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

pytestmark = pytest.mark.usefixtures("user")


async def count(session: AsyncSession, model: type) -> int:
    return (await session.exec(select(func.count()).select_from(model))).one()


async def create(client: AsyncClient, policy: Policy, text: str = "班機取消了") -> dict:
    response = await client.post(
        f"/policies/{policy.id}/incidents",
        json={"description": text, "destination": "日本"},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_creating_an_incident_prefills_coverages_and_basic_todos(
    client: AsyncClient, session: AsyncSession, policy: Policy
) -> None:
    body = await create(client, policy)
    incident = body["incident"]
    # 平台預先放入：保單涵蓋的保障（之後 5 可以細修）、事件問答對話；
    # 待辦要等 5 問完、判斷出類型才產生（v3.3），所以一開始是空的
    assert incident["status"] == "open"
    assert incident["policy"]["plan_id"] == "fubon_advanced"
    assert len(incident["clauses"]) > 0 or body["reply"]["clauses"] is not None
    assert incident["todos"] == []
    # 然後叫起 5：第一則助手訊息就是追問
    assert body["reply"]["message"]
    assert [m["role"] for m in incident["messages"]] == ["user", "assistant"]
    conversation = (
        await session.exec(
            select(Conversation).where(Conversation.kind == "incident_qa")
        )
    ).one()
    assert str(conversation.incident_id) == incident["incident_id"]


async def test_full_flow_from_message_to_submission(
    client: AsyncClient, session: AsyncSession, policy: Policy
) -> None:
    incident_id = (await create(client, policy))["incident"]["incident_id"]

    # 5：先問、問完才回類型並產生待辦（v3.3）。
    # 要問幾題由 5 決定（真實的 5 要問完所有必問欄位），所以第一句說明狀況，之後一直回「不知道」
    # 直到 finished（v3.4：選「不知道」視為已回答，一定會結束），並設上限避免無限迴圈。
    max_rounds = 15
    for round_no in range(max_rounds):
        content = "班機延誤了六小時" if round_no == 0 else "不知道"
        response = await client.post(
            f"/incidents/{incident_id}/messages", json={"content": content}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        if body["reply"]["finished"]:
            break
        # 問的過程中：還沒有類型，也沒有該類型的待辦
        assert body["incident"]["incident_type_code"] in (None, "other")
        assert not any("延誤" in t["title"] for t in body["incident"]["todos"])
    else:
        pytest.fail(f"問了 {max_rounds} 輪還沒結束（finished 一直是 False）")

    # 問完 → 判斷類型、更新狀況與待辦、附出處
    state = body["incident"]
    assert state["incident_type_code"] == "flight_delay"
    assert state["facts"]
    assert any("延誤" in t["title"] for t in state["todos"]), "該類型的待辦範本要補進來"
    assert len({(t["phase"], t["title"]) for t in state["todos"]}) == len(
        state["todos"]
    )
    assert await count(session, MessageCitation) >= 1
    assert await count(session, IncidentFact) >= 1

    # 6：上傳文件 → 辨識、存雲端、勾選待辦
    upload = await client.post(
        f"/incidents/{incident_id}/documents",
        files={"file": ("延誤證明.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert upload.status_code == 201, upload.text
    assert upload.json()["recognition_status"] == "recognized"
    document = (await session.exec(select(IncidentDocument))).one()
    assert document.storage_path and document.incident_todo_id
    todo = await session.get(IncidentTodo, document.incident_todo_id)
    assert todo and todo.is_done and todo.done_by == "agent"

    # 還有待辦沒完成：不能送件
    blocked = await client.post(
        f"/incidents/{incident_id}/submission", json={"recipient": "claims@example.com"}
    )
    assert blocked.status_code == 409

    # 勾完其他待辦：不需上傳的手動勾；需上傳的靠上傳（假辨識會勾第一個沒完成的待辦）
    for _ in range(20):
        undone = [
            t
            for t in (await client.get(f"/incidents/{incident_id}")).json()["todos"]
            if not t["is_done"]
        ]
        if not undone:
            break
        # 契約的 TodoView 還沒有 requires_upload（agent 6 的 B3），先用 409 判斷要上傳
        patched = await client.patch(
            f"/incidents/{incident_id}/todos/{undone[0]['id']}", json={"is_done": True}
        )
        if patched.status_code == 409:
            uploaded = await client.post(
                f"/incidents/{incident_id}/documents",
                files={"file": ("證明.pdf", b"%PDF-1.4", "application/pdf")},
            )
            assert uploaded.status_code == 201, uploaded.text
        else:
            assert patched.status_code == 200
    final = (await client.get(f"/incidents/{incident_id}")).json()
    assert all(t["is_done"] for t in final["todos"])
    assert "agent" in {t["done_by"] for t in final["todos"]}

    # 7：預覽送件包 → 寄出
    package = (await client.get(f"/incidents/{incident_id}/package")).json()
    assert package["missing_todo_ids"] == []
    assert "延誤證明.pdf" in [a["file_name"] for a in package["attachments"]]
    sent = await client.post(
        f"/incidents/{incident_id}/submission", json={"recipient": "claims@example.com"}
    )
    assert sent.status_code == 201, sent.text
    assert sent.json()["status"] == "sent"
    assert (await client.get(f"/incidents/{incident_id}")).json()[
        "status"
    ] == "completed"
    assert (await session.exec(select(PolicySubmission))).one().gmail_refs
    incident = await session.get(Incident, uuid.UUID(incident_id))
    assert incident and incident.status == "completed"


async def test_clauses_after_5_are_within_the_policy_coverage(
    client: AsyncClient, policy: Policy
) -> None:
    incident_id = (await create(client, policy))["incident"]["incident_id"]
    state = (
        await client.post(
            f"/incidents/{incident_id}/messages", json={"content": "班機延誤"}
        )
    ).json()["incident"]
    covered = {
        (c["insurance_code"], c["section"]) for c in state["policy"]["coverages"]
    }
    assert state["clauses"]
    for c in state["clauses"]:
        assert (c["insurance_code"], c["section"]) in covered or (
            c["insurance_code"],
            None,
        ) in covered


async def test_unrecognized_document_does_not_tick_a_todo(
    client: AsyncClient, session: AsyncSession, policy: Policy
) -> None:
    incident_id = (await create(client, policy))["incident"]["incident_id"]
    upload = await client.post(
        f"/incidents/{incident_id}/documents",
        files={"file": ("random.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert upload.status_code == 201
    assert upload.json()["recognition_status"] == "needs_review"
    assert upload.json()["reason"]
    assert not any(t.is_done for t in (await session.exec(select(IncidentTodo))).all())


async def test_clause_rows_are_seeded_for_the_new_incident(
    client: AsyncClient, session: AsyncSession, policy: Policy
) -> None:
    await create(client, policy)
    assert await count(session, IncidentClause) > 0
    assert await count(session, Message) == 2
