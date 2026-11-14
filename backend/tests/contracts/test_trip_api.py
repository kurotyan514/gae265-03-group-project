"""行程（一張保單）層級的 API（ADR-0029）：行程頁、共同待辦、整個行程一次送件、結案與鎖住。"""

import uuid

import pytest
from app.contracts import ClaimPackage
from app.models import Incident, IncidentTodo, Policy
from httpx import AsyncClient
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

pytestmark = pytest.mark.usefixtures("user")


async def new_incident(
    client: AsyncClient, policy: Policy, text: str = "班機延誤了六小時"
) -> str:
    """建立事件，並一直回答到 5 結束（產生類型、結論與待辦）。"""
    created = await client.post(
        f"/policies/{policy.id}/incidents", json={"description": text}
    )
    assert created.status_code == 201, created.text
    incident_id = created.json()["incident"]["incident_id"]
    for _ in range(15):
        body = (
            await client.post(
                f"/incidents/{incident_id}/messages", json={"content": text}
            )
        ).json()
        if body["reply"]["finished"]:
            return incident_id
    raise AssertionError("5 一直沒結束")


async def trip(client: AsyncClient, policy: Policy) -> dict:
    response = await client.get(f"/policies/{policy.id}/trip")
    assert response.status_code == 200, response.text
    return response.json()


async def finish_all_todos(session: AsyncSession) -> None:
    for todo in (await session.exec(select(IncidentTodo))).all():
        todo.status = "done"
        todo.done_by = "user"
        session.add(todo)
    await session.commit()


async def test_行程頁把共同文件放在行程底下_事件只有自己的待辦(
    client: AsyncClient, policy: Policy
) -> None:
    await new_incident(client, policy)

    body = await trip(client, policy)

    assert body["status"] == "open" and body["locked"] is False
    shared = {t["document_code"] for t in body["shared_todos"]}
    assert "D10" in shared  # 理賠申請書
    assert all(t["incident_id"] is None for t in body["shared_todos"])
    incident = body["incidents"][0]
    assert incident["covered"] is True
    assert all(t["incident_id"] == incident["id"] for t in incident["todos"])
    assert not shared & {t["document_code"] for t in incident["todos"]}
    assert body["can_submit"] is False  # 待辦還沒完成


async def test_兩個事件共用同一組共同待辦_不重複建立(
    client: AsyncClient, policy: Policy
) -> None:
    await new_incident(client, policy)
    first = {t["id"] for t in (await trip(client, policy))["shared_todos"]}

    await new_incident(client, policy, "班機取消了")

    body = await trip(client, policy)
    assert len(body["incidents"]) == 2
    assert {t["id"] for t in body["shared_todos"]} == first


async def test_我的行程只列有事件的保單(client: AsyncClient, policy: Policy) -> None:
    assert (await client.get("/trips")).json() == []
    assert (await client.get(f"/policies/{policy.id}/trip")).status_code == 404

    await new_incident(client, policy)

    trips = (await client.get("/trips")).json()
    assert [t["policy_id"] for t in trips] == [str(policy.id)]
    assert trips[0]["incident_count"] == 1 and trips[0]["locked"] is False


async def test_別人的行程回_404(client: AsyncClient, session: AsyncSession) -> None:
    from app.models import User

    other = User(email="other@example.com")
    session.add(other)
    await session.flush()
    foreign = Policy(user_id=other.id, display_name="別人", plan_id="x", sum_insured=1)
    session.add(foreign)
    await session.commit()

    for path in ("trip", "submission", "package"):
        assert (await client.get(f"/policies/{foreign.id}/{path}")).status_code == 404
    assert (await client.post(f"/policies/{foreign.id}/close")).status_code == 404


async def test_待辦沒完成不能送件(client: AsyncClient, policy: Policy) -> None:
    await new_incident(client, policy)

    response = await client.post(
        f"/policies/{policy.id}/submission", json={"mode": "self"}
    )

    assert response.status_code == 409 and "待辦" in response.json()["detail"]


async def test_自己處理_整個行程一起結案並鎖住(
    client: AsyncClient, policy: Policy, session: AsyncSession
) -> None:
    await new_incident(client, policy)
    await new_incident(client, policy, "班機取消了")
    await finish_all_todos(session)
    assert (await trip(client, policy))["can_submit"] is True

    response = await client.post(
        f"/policies/{policy.id}/submission", json={"mode": "self"}
    )

    assert response.status_code == 201, response.text
    body = await trip(client, policy)
    assert body["status"] == "completed" and body["locked"] is True
    assert {i["status"] for i in body["incidents"]} == {"completed"}
    assert body["submission"]["status"] == "self_submitted"
    submission = (await client.get(f"/policies/{policy.id}/submission")).json()
    assert submission["status"] == "self_submitted"
    # 鎖住：不能再送件、不能再新增事件
    again = await client.post(
        f"/policies/{policy.id}/submission", json={"mode": "self"}
    )
    assert again.status_code == 409
    new = await client.post(
        f"/policies/{policy.id}/incidents", json={"description": "又出事了"}
    )
    assert new.status_code == 409 and "行程" in new.json()["detail"]


async def test_假的_7_號有行程版_一封信寄出整個行程(
    client: AsyncClient, policy: Policy, session: AsyncSession
) -> None:
    await new_incident(client, policy)
    await finish_all_todos(session)

    preview = await client.get(f"/policies/{policy.id}/package")
    assert preview.status_code == 200 and preview.json()["missing_todo_ids"] == []

    response = await client.post(
        f"/policies/{policy.id}/submission",
        json={"mode": "send", "recipient": "claims@example.com"},
    )

    assert response.status_code == 201, response.text
    assert response.json()["status"] == "sent"
    incidents = (await session.exec(select(Incident))).all()
    assert {i.status for i in incidents} == {"completed"}


class LegacyPackager:
    """還沒有行程版的 7 號：只有舊的 build、send。"""

    async def build(self, ctx, google=None, user=None) -> ClaimPackage:  # type: ignore[no-untyped-def]
        return ClaimPackage(subject="舊", body=f"事件 {ctx.title}", attachments=[])

    async def send(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("沒有行程版時不該寄出")


async def test_7_號沒有行程版_只能預覽與自己處理_寄出回_409(
    client: AsyncClient,
    policy: Policy,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.api.routes.trip.get_claim_packager", lambda: LegacyPackager()
    )
    await new_incident(client, policy)
    await new_incident(client, policy, "班機取消了")
    await finish_all_todos(session)

    preview = (await client.get(f"/policies/{policy.id}/package")).json()
    assert preview["body"].count("【") == 2  # 兩個事件各一段

    for mode in ("send", "draft"):
        response = await client.post(
            f"/policies/{policy.id}/submission",
            json={"mode": mode, "recipient": "claims@example.com"},
        )
        assert response.status_code == 409, mode
    self_ = await client.post(
        f"/policies/{policy.id}/submission", json={"mode": "self"}
    )
    assert self_.status_code == 201


async def test_全部事件都不符保障時可以結案_不寄信也不寫送件紀錄(
    client: AsyncClient, policy: Policy
) -> None:
    await new_incident(client, policy, "班機延誤了但是不理賠")
    body = await trip(client, policy)
    assert body["incidents"][0]["covered"] is False
    assert body["can_close"] is True and body["can_submit"] is False
    assert body["shared_todos"] == []  # 不符保障就不建共同待辦
    blocked = await client.post(
        f"/policies/{policy.id}/submission", json={"mode": "self"}
    )
    assert blocked.status_code == 409

    response = await client.post(f"/policies/{policy.id}/close")

    assert response.status_code == 200, response.text
    body = await trip(client, policy)
    assert body["locked"] is True and body["submission"]["status"] is None


async def test_還有符合保障的事件不能結案(client: AsyncClient, policy: Policy) -> None:
    await new_incident(client, policy)

    response = await client.post(f"/policies/{policy.id}/close")

    assert response.status_code == 409


async def test_不符保障的事件不擋送件_其他事件完成就可以(
    client: AsyncClient, policy: Policy, session: AsyncSession
) -> None:
    await new_incident(client, policy)
    await new_incident(client, policy, "班機延誤了但是不理賠")
    await finish_all_todos(session)

    body = await trip(client, policy)

    assert [i["covered"] for i in body["incidents"]].count(False) == 1
    assert body["can_submit"] is True and body["can_close"] is False


async def test_共同待辦的適用性依涵蓋中的事件聚合(
    client: AsyncClient, policy: Policy, session: AsyncSession
) -> None:
    from app.domain.incident.service import refresh_shared_todos

    await new_incident(client, policy)
    shared = (
        await session.exec(
            select(IncidentTodo).where(col(IncidentTodo.policy_id).is_not(None))
        )
    ).all()
    assert shared and all(t.applicable for t in shared)

    # 唯一的事件不再涵蓋（結論全改成 excluded）：共同待辦跟著不適用；之後又適用就標新增
    from app.models import IncidentClause

    clauses = (await session.exec(select(IncidentClause))).all()
    for c in clauses:
        c.conclusion = "excluded"
        session.add(c)
    await session.flush()
    await refresh_shared_todos(session, policy.id)
    assert not any(t.applicable for t in shared)

    for c in clauses:
        c.conclusion = "applicable"
        session.add(c)
    await session.flush()
    await refresh_shared_todos(session, policy.id)
    assert all(t.applicable and t.is_new for t in shared)
    assert uuid.UUID(str(shared[0].policy_id)) == policy.id
