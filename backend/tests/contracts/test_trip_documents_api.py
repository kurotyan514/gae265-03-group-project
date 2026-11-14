"""行程層級的文件與待辦動作（ADR-0029）：一個上傳框，文件對到共同文件或任一事件的待辦。"""

import datetime as dt
import uuid

import pytest
from app.contracts import Recognition, UploadedFile
from app.contracts.fakes import FakeDocumentRecognizer
from app.models import Incident, IncidentDocument, Policy
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from .test_trip_api import new_incident, trip

pytestmark = pytest.mark.usefixtures("user")


def upload(client: AsyncClient, policy: Policy, name: str, todo_id: str | None = None):
    return client.post(
        f"/policies/{policy.id}/documents",
        files={"file": (name, b"%PDF-1.4", "application/pdf")},
        data={"todo_id": todo_id} if todo_id else {},
    )


def shared_todo(body: dict, code: str = "D10") -> dict:
    return next(t for t in body["shared_todos"] if t["document_code"] == code)


async def two_incidents(client: AsyncClient, policy: Policy) -> dict:
    await new_incident(client, policy)
    await new_incident(client, policy, "班機取消了")
    return await trip(client, policy)


async def test_共同文件上傳_文件掛在保單上_檔名是共同文件(
    client: AsyncClient, policy: Policy, session: AsyncSession
) -> None:
    await new_incident(client, policy)
    todo = shared_todo(await trip(client, policy))

    response = await upload(client, policy, "診斷.pdf", todo["id"])

    assert response.status_code == 201, response.text
    assert response.json()["recognition_status"] == "recognized"
    document = (await session.exec(select(IncidentDocument))).one()
    assert document.incident_id is None and document.policy_id == policy.id
    assert document.incident_todo_id == uuid.UUID(todo["id"])
    assert document.file_name.startswith("共同文件_")
    body = await trip(client, policy)
    assert [d["id"] for d in body["shared_documents"]] == [str(document.id)]
    assert shared_todo(body)["status"] == "done"
    assert body["incidents"][0]["documents"] == []


async def test_事件待辦上傳_文件掛在那個事件(
    client: AsyncClient, policy: Policy, session: AsyncSession
) -> None:
    body = await two_incidents(client, policy)
    second = body["incidents"][1]
    todo = second["todos"][0]

    response = await upload(client, policy, "證明.pdf", todo["id"])

    assert response.status_code == 201, response.text
    document = (await session.exec(select(IncidentDocument))).one()
    assert str(document.incident_id) == second["id"] and document.policy_id is None
    assert document.file_name.startswith(second["incident_type_name"])


async def test_歧義時需要確認_確認後文件換成待辦所屬的事件(
    client: AsyncClient, policy: Policy, session: AsyncSession
) -> None:
    body = await two_incidents(client, policy)

    pending = await upload(client, policy, "歧義.pdf")

    assert pending.status_code == 201, pending.text
    out = pending.json()
    assert out["recognition_status"] == "needs_review" and out["todo_id"] is None
    candidates = set(out["candidate_todo_ids"])
    first = body["incidents"][0]["todos"][0]
    second = body["incidents"][1]["todos"][0]
    assert {first["id"], second["id"]} <= candidates
    document = (await session.exec(select(IncidentDocument))).one()
    assert document.policy_id == policy.id and document.incident_id is None  # 先掛保單

    confirmed = await client.post(
        f"/policies/{policy.id}/documents/{out['id']}/confirm",
        json={"todo_id": second["id"]},
    )

    assert confirmed.status_code == 200, confirmed.text
    await session.refresh(document)
    assert str(document.incident_id) == body["incidents"][1]["id"]
    assert document.policy_id is None and document.confirmed_by_user is True
    after = confirmed.json()
    assert after["incidents"][1]["documents"][0]["id"] == out["id"]
    assert (
        next(t for t in after["incidents"][1]["todos"] if t["id"] == second["id"])[
            "done_by"
        ]
        == "user"
    )


async def test_重新檢查通過_由_6_號勾起待辦(
    client: AsyncClient, policy: Policy
) -> None:
    body = await two_incidents(client, policy)
    out = (await upload(client, policy, "歧義.pdf")).json()
    target = body["incidents"][0]["todos"][0]

    response = await client.post(
        f"/policies/{policy.id}/documents/{out['id']}/recheck",
        json={"todo_id": target["id"]},
    )

    assert response.status_code == 200, response.text
    assert response.json()["recognition_status"] == "recognized"
    assert response.json()["todo_complete"] is True
    after = await trip(client, policy)
    todo = next(t for t in after["incidents"][0]["todos"] if t["id"] == target["id"])
    assert todo["status"] == "done" and todo["done_by"] == "agent"
    assert after["incidents"][0]["documents"][0]["id"] == out["id"]


async def test_重新檢查不合格_6_號刪檔_紀錄拿掉(
    client: AsyncClient, policy: Policy, session: AsyncSession
) -> None:
    body = await two_incidents(client, policy)
    out = (await upload(client, policy, "歧義.pdf")).json()
    # 假的 6 號重新檢查看存檔的檔名：含「缺」就回 incomplete
    document = (await session.exec(select(IncidentDocument))).one()
    document.file_name = "缺頁.pdf"
    session.add(document)
    await session.commit()

    response = await client.post(
        f"/policies/{policy.id}/documents/{out['id']}/recheck",
        json={"todo_id": body["incidents"][0]["todos"][0]["id"]},
    )

    assert response.status_code == 200, response.text
    assert response.json()["recognition_status"] == "incomplete"
    assert response.json()["missing"] == ["最後一頁"]
    assert (await session.exec(select(IncidentDocument))).all() == []


async def test_都不是_刪掉文件與紀錄(
    client: AsyncClient, policy: Policy, session: AsyncSession
) -> None:
    await two_incidents(client, policy)
    out = (await upload(client, policy, "歧義.pdf")).json()

    response = await client.post(f"/policies/{policy.id}/documents/{out['id']}/reject")

    assert response.status_code == 200, response.text
    assert (await session.exec(select(IncidentDocument))).all() == []


async def test_打開行程時清掉上次沒選的暫存檔(
    client: AsyncClient, policy: Policy, session: AsyncSession
) -> None:
    await two_incidents(client, policy)
    await upload(client, policy, "歧義.pdf")
    later = (dt.datetime.now(dt.UTC) + dt.timedelta(minutes=1)).isoformat()

    response = await client.post(
        f"/policies/{policy.id}/documents/discard-pending", json={"before": later}
    )

    assert response.status_code == 200, response.text
    assert (await session.exec(select(IncidentDocument))).all() == []


async def test_不符保障的事件不能上傳也不能勾(
    client: AsyncClient, policy: Policy
) -> None:
    await new_incident(client, policy)
    await new_incident(client, policy, "班機延誤了但是不理賠")
    body = await trip(client, policy)
    # 不符保障的事件沒有待辦（假的 5 號不給）：用事件待辦的 id 驗不到；改驗不存在的待辦 404
    assert body["incidents"][1]["covered"] is False
    missing = await upload(client, policy, "診斷.pdf", str(uuid.uuid4()))
    assert missing.status_code == 404


async def test_5_號自己加的待辦不能上傳但可以勾(
    client: AsyncClient, policy: Policy, session: AsyncSession
) -> None:
    from app.models import IncidentTodo

    await new_incident(client, policy)
    incident = (await session.exec(select(Incident))).one()
    extra = IncidentTodo(
        incident_id=incident.id, phase="after_return", title="向保險公司確認"
    )
    session.add(extra)
    await session.commit()

    refused = await upload(client, policy, "診斷.pdf", str(extra.id))
    ticked = await client.patch(
        f"/policies/{policy.id}/todos/{extra.id}", json={"is_done": True}
    )

    assert refused.status_code == 409
    assert ticked.status_code == 200, ticked.text
    body = ticked.json()
    assert (
        next(t for t in body["incidents"][0]["todos"] if t["id"] == str(extra.id))[
            "status"
        ]
        == "done"
    )
    assert body["can_submit"] is False  # 不計入送件檢查，但其他待辦還沒完成


async def test_勾選共同待辦_需上傳的標未附文件(
    client: AsyncClient, policy: Policy
) -> None:
    await new_incident(client, policy)
    todo = shared_todo(await trip(client, policy), "D02")

    ticked = await client.patch(
        f"/policies/{policy.id}/todos/{todo['id']}", json={"is_done": True}
    )

    assert ticked.status_code == 200, ticked.text
    after = shared_todo(ticked.json(), "D02")
    assert after["status"] == "done" and after["without_document"] is True
    cleared = await client.patch(
        f"/policies/{policy.id}/todos/{todo['id']}", json={"is_done": False}
    )
    assert shared_todo(cleared.json(), "D02")["without_document"] is False


async def test_行程鎖住後所有文件動作回_409(
    client: AsyncClient, policy: Policy, session: AsyncSession
) -> None:
    await new_incident(client, policy)
    todo = shared_todo(await trip(client, policy))
    for incident in (await session.exec(select(Incident))).all():
        incident.status = "completed"
        session.add(incident)
    await session.commit()

    calls = [
        upload(client, policy, "診斷.pdf", todo["id"]),
        client.patch(
            f"/policies/{policy.id}/todos/{todo['id']}", json={"is_done": True}
        ),
        client.post(
            f"/policies/{policy.id}/documents/discard-pending",
            json={"before": dt.datetime.now(dt.UTC).isoformat()},
        ),
    ]
    for call in calls:
        assert (await call).status_code == 409


async def test_別人的行程_404(client: AsyncClient, session: AsyncSession) -> None:
    from app.models import User

    other = User(email="other2@example.com")
    session.add(other)
    await session.flush()
    foreign = Policy(user_id=other.id, display_name="別人", plan_id="x", sum_insured=1)
    session.add(foreign)
    await session.commit()

    response = await upload(client, foreign, "診斷.pdf")

    assert response.status_code == 404


class LegacyRecognizer:
    """還沒有行程版的 6 號：只有舊的 recognize，委託給假實作。"""

    async def recognize(self, ctx, file: UploadedFile, user, google) -> Recognition:  # type: ignore[no-untyped-def]
        return await FakeDocumentRecognizer().recognize(ctx, file, user, google)


async def test_6_號沒有行程版_指定待辦時退回逐事件辨識(
    client: AsyncClient, policy: Policy, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.api.routes.trip_documents.get_document_recognizer",
        lambda: LegacyRecognizer(),
    )
    body = await two_incidents(client, policy)
    todo = body["incidents"][1]["todos"][0]

    response = await upload(client, policy, "證明.pdf", todo["id"])

    assert response.status_code == 201, response.text
    assert response.json()["todo_id"] == todo["id"]


async def test_6_號沒有行程版_沒指定待辦而且有多個事件時_409(
    client: AsyncClient, policy: Policy, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.api.routes.trip_documents.get_document_recognizer",
        lambda: LegacyRecognizer(),
    )
    await two_incidents(client, policy)

    response = await upload(client, policy, "證明.pdf")

    assert response.status_code == 409 and "待辦" in response.json()["detail"]
