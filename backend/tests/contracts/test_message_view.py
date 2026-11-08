"""重新整理事件頁後，5 號回覆的快速選項與條文出處要還原（契約 2.3.0，#212）。

後端本來就有存（`Message.quick_replies`、`MessageCitation`），`MessageView` 要帶出來；
每則 5 號訊息各自帶自己的，使用者的訊息兩者都是空的。
"""

import pytest
from app.contracts import CONTRACT_VERSION
from app.models import Policy
from httpx import AsyncClient

pytestmark = pytest.mark.usefixtures("user")


async def messages_of(client: AsyncClient, incident_id: str) -> list[dict]:
    response = await client.get(f"/incidents/{incident_id}")
    assert response.status_code == 200, response.text
    return response.json()["messages"]


async def run_until_citations(
    client: AsyncClient, policy: Policy
) -> tuple[str, list[dict]]:
    """用假 5 號問到它回出處為止；回傳事件編號與每一輪回覆的 citations。"""
    created = await client.post(
        f"/policies/{policy.id}/incidents", json={"description": "班機延誤了"}
    )
    assert created.status_code == 201, created.text
    incident_id = created.json()["incident"]["incident_id"]
    replies = [created.json()["reply"]]
    for _ in range(5):
        if replies[-1]["citations"]:
            break
        sent = await client.post(
            f"/incidents/{incident_id}/messages", json={"content": "班機延誤了"}
        )
        assert sent.status_code == 200, sent.text
        replies.append(sent.json()["reply"])
    assert replies[-1]["citations"], "假 5 號應該在問完後回出處"
    return incident_id, replies


def test_契約版本是_2_5_0() -> None:
    assert CONTRACT_VERSION == "2.5.0"


@pytest.mark.usefixtures("catalog_loaded")
async def test_每則_5_號訊息帶出自己的快速選項與出處(
    client: AsyncClient, policy: Policy
) -> None:
    incident_id, replies = await run_until_citations(client, policy)

    assistant = [
        m for m in await messages_of(client, incident_id) if m["role"] == "assistant"
    ]

    assert len(assistant) == len(replies)
    for message, reply in zip(assistant, replies, strict=True):
        assert message["quick_replies"] == (reply["quick_replies"] or [])
        assert [
            (c["insurance_code"], c["article_no"]) for c in message["citations"]
        ] == [(c["insurance_code"], c["article_no"]) for c in reply["citations"]]
    # 第一則有選項、沒有出處；最後一則有出處（各自的，不是共用同一組）
    assert assistant[0]["quick_replies"] and assistant[0]["citations"] == []
    assert assistant[-1]["citations"]


@pytest.mark.usefixtures("catalog_loaded")
async def test_使用者的訊息沒有選項也沒有出處(
    client: AsyncClient, policy: Policy
) -> None:
    incident_id, _ = await run_until_citations(client, policy)

    users = [m for m in await messages_of(client, incident_id) if m["role"] == "user"]

    assert users
    assert all(m["quick_replies"] == [] and m["citations"] == [] for m in users)
