"""待辦的「未附文件」（`without_document`）只該標在真的沒有文件的待辦上（#166）。

走查發現：6 號辨識了登機證但提示還缺機票，使用者自己勾掉那項待辦，平台仍標「未附文件」，
7 號的送件信就同時寫「未隨信附上」與列在附件清單，互相矛盾。
"""

import uuid

import pytest
from app.models import IncidentDocument, IncidentTodo, Policy
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

pytestmark = pytest.mark.usefixtures("user")


async def setup_todo(
    client: AsyncClient,
    session: AsyncSession,
    policy: Policy,
    *,
    document: str | None = None,
    confirmed: bool = False,
) -> tuple[str, str, IncidentDocument | None]:
    """一個事件、一項需上傳的待辦；可以附一份指定辨識狀態的文件。回傳（事件、待辦、文件）。"""
    created = await client.post(
        f"/policies/{policy.id}/incidents", json={"description": "班機延誤了"}
    )
    incident_id = created.json()["incident"]["incident_id"]
    todo = IncidentTodo(
        incident_id=incident_id,
        phase="after_return",
        title="機票及登機證",
        requires_upload=True,
        sort_order=0,
    )
    session.add(todo)
    await session.commit()
    doc = None
    if document:
        doc = IncidentDocument(
            incident_id=incident_id,
            incident_todo_id=todo.id,
            file_name="登機證.pdf",
            storage_path="drive-file-1",
            content_type="application/pdf",
            size_bytes=10,
            recognition_status=document,
            confirmed_by_user=confirmed,
        )
        session.add(doc)
        await session.commit()
    return incident_id, str(todo.id), doc


async def tick(client: AsyncClient, incident_id: str, todo_id: str, done: bool) -> dict:
    response = await client.patch(
        f"/incidents/{incident_id}/todos/{todo_id}", json={"is_done": done}
    )
    assert response.status_code == 200, response.text
    return next(t for t in response.json()["todos"] if t["id"] == todo_id)


async def test_ticking_a_todo_with_a_recognized_document_is_not_without_document(
    client: AsyncClient, session: AsyncSession, policy: Policy
) -> None:
    i, t, _ = await setup_todo(client, session, policy, document="recognized")

    todo = await tick(client, i, t, True)

    assert todo["is_done"] is True
    assert todo["without_document"] is False


async def test_ticking_a_todo_with_a_confirmed_document_is_not_without_document(
    client: AsyncClient, session: AsyncSession, policy: Policy
) -> None:
    i, t, _ = await setup_todo(
        client, session, policy, document="needs_review", confirmed=True
    )

    assert (await tick(client, i, t, True))["without_document"] is False


async def test_ticking_a_todo_without_any_document_is_without_document_until_unticked(
    client: AsyncClient, session: AsyncSession, policy: Policy
) -> None:
    i, t, _ = await setup_todo(client, session, policy)

    assert (await tick(client, i, t, True))["without_document"] is True
    assert (await tick(client, i, t, False))["without_document"] is False


async def test_an_unconfirmed_document_does_not_count_as_attached(
    client: AsyncClient, session: AsyncSession, policy: Policy
) -> None:
    # 「需人工確認」又還沒確認的文件不會進送件包，所以這項仍是沒附文件
    i, t, _ = await setup_todo(client, session, policy, document="needs_review")

    assert (await tick(client, i, t, True))["without_document"] is True


async def test_confirming_a_document_onto_an_already_ticked_todo_clears_the_flag(
    client: AsyncClient, session: AsyncSession, policy: Policy
) -> None:
    i, t, _ = await setup_todo(client, session, policy)
    assert (await tick(client, i, t, True))["without_document"] is True
    review = IncidentDocument(
        incident_id=uuid.UUID(i),
        file_name="補件.pdf",
        storage_path="drive-file-2",
        content_type="application/pdf",
        size_bytes=10,
        recognition_status="needs_review",
    )
    session.add(review)
    await session.commit()

    confirmed = await client.post(
        f"/incidents/{i}/documents/{review.id}/confirm", json={"todo_id": t}
    )

    assert confirmed.status_code == 200, confirmed.text
    todo = next(x for x in confirmed.json()["todos"] if x["id"] == t)
    assert todo["without_document"] is False


# 確認後的檔名（#160）


class _Renamer:
    """有 rename_confirmed 的 6 號替身：回傳固定的新檔名，或改不了（None）。"""

    def __init__(self, name: str | None) -> None:
        self.name = name
        self.calls = 0

    async def rename_confirmed(self, ctx, document, todo, user, google):
        self.calls += 1
        return self.name


async def _confirm(
    client: AsyncClient,
    session: AsyncSession,
    policy: Policy,
    monkeypatch: pytest.MonkeyPatch,
    recognizer: object,
) -> IncidentDocument:
    i, t, _ = await setup_todo(client, session, policy)
    review = IncidentDocument(
        incident_id=uuid.UUID(i),
        file_name="班機延誤_待確認_1.pdf",
        storage_path="drive-file-2",
        content_type="application/pdf",
        size_bytes=10,
        recognition_status="needs_review",
    )
    session.add(review)
    await session.commit()
    monkeypatch.setattr(
        "app.api.routes.incidents.get_document_recognizer", lambda: recognizer
    )
    confirmed = await client.post(
        f"/incidents/{i}/documents/{review.id}/confirm", json={"todo_id": t}
    )
    assert confirmed.status_code == 200, confirmed.text
    await session.refresh(review)
    return review


async def test_confirming_renames_the_document_for_the_package(
    client: AsyncClient,
    session: AsyncSession,
    policy: Policy,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renamer = _Renamer("班機延誤_機票及登機證_1.pdf")

    document = await _confirm(client, session, policy, monkeypatch, renamer)

    assert renamer.calls == 1
    assert document.file_name == "班機延誤_機票及登機證_1.pdf"


async def test_a_failed_rename_keeps_the_old_name_and_still_confirms(
    client: AsyncClient,
    session: AsyncSession,
    policy: Policy,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = await _confirm(client, session, policy, monkeypatch, _Renamer(None))

    assert document.confirmed_by_user is True
    assert document.file_name == "班機延誤_待確認_1.pdf"


async def test_a_recognizer_without_rename_keeps_the_old_name(
    client: AsyncClient,
    session: AsyncSession,
    policy: Policy,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = await _confirm(client, session, policy, monkeypatch, object())

    assert document.confirmed_by_user is True
    assert document.file_name == "班機延誤_待確認_1.pdf"
