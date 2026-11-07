"""事件結案（status == completed）後鎖住（#152）：不能再傳訊息、改待辦、上傳或確認文件、送件。

走查發現結案後再送件一次也成功，真的寄信會寄出重複的信。
"""

import uuid

import pytest
from app.models import Incident, Policy
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

pytestmark = pytest.mark.usefixtures("user")

CLOSED = "事件已結案，不能修改"


async def closed_incident(
    client: AsyncClient, session: AsyncSession, policy: Policy
) -> uuid.UUID:
    created = await client.post(
        f"/policies/{policy.id}/incidents", json={"description": "班機延誤了"}
    )
    assert created.status_code == 201, created.text
    incident_id = uuid.UUID(created.json()["incident"]["incident_id"])
    incident = await session.get(Incident, incident_id)
    assert incident is not None
    incident.status = "completed"
    session.add(incident)
    await session.commit()
    return incident_id


async def test_closed_incident_rejects_every_change(
    client: AsyncClient, session: AsyncSession, policy: Policy
) -> None:
    i = await closed_incident(client, session, policy)
    calls = {
        "傳訊息": client.post(f"/incidents/{i}/messages", json={"content": "補充"}),
        "改待辦": client.patch(
            f"/incidents/{i}/todos/{uuid.uuid4()}", json={"is_done": True}
        ),
        "上傳文件": client.post(
            f"/incidents/{i}/documents",
            files={"file": ("a.pdf", b"%PDF-1.4", "application/pdf")},
        ),
        "確認文件": client.post(
            f"/incidents/{i}/documents/{uuid.uuid4()}/confirm",
            json={"todo_id": str(uuid.uuid4())},
        ),
        "送件": client.post(
            f"/incidents/{i}/submission", json={"recipient": "claims@example.com"}
        ),
    }
    for name, call in calls.items():
        response = await call
        assert response.status_code == 409, f"{name}：{response.status_code}"
        assert response.json()["detail"] == CLOSED, name


async def test_closed_incident_can_still_be_read(
    client: AsyncClient, session: AsyncSession, policy: Policy
) -> None:
    i = await closed_incident(client, session, policy)

    got = await client.get(f"/incidents/{i}")
    assert got.status_code == 200
    assert got.json()["status"] == "completed"
    assert (await client.get(f"/incidents/{i}/package")).status_code == 200
    assert any(row["id"] == str(i) for row in (await client.get("/incidents")).json())
