"""送件 API 收「做什麼（mode）」「填好的空格（fills）」「收件者」（#151、ADR-0025）。

用會記錄呼叫的 7 號：檢查平台把填好的值放進信、什麼情況呼叫 7 號、依結果寫送件紀錄與結案。
"""

import pytest
from app.agents import registry
from app.contracts import (
    ClaimPackage,
    GoogleAccess,
    IncidentContext,
    SendResult,
    UserContext,
)
from app.core.config import settings
from app.models import Incident, IncidentTodo, Policy, PolicySubmission
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

pytestmark = pytest.mark.usefixtures("user")

SUBJECT = "理賠申請：（請填寫保單號碼）"
BODY = "被保險人：（請填寫被保險人姓名）\n保單號碼：（請填寫保單號碼）\n保額：6000000"


class Recorder:
    """假的 7 號：build 固定回有空格的信，send 記下收到的東西。"""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.result = SendResult(status="sent", external_ref="msg-1")

    async def build(self, ctx: IncidentContext) -> ClaimPackage:
        return ClaimPackage(subject=SUBJECT, body=BODY)

    async def send(
        self,
        ctx: IncidentContext,
        package: ClaimPackage,
        recipient: str | None,
        user: UserContext,
        google: GoogleAccess,
        mode: str = "send",
    ) -> SendResult:
        self.sent.append(
            {
                "subject": package.subject,
                "body": package.body,
                "recipient": recipient,
                "mode": mode,
            }
        )
        return self.result


@pytest.fixture
def seven(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    recorder = Recorder()
    monkeypatch.setitem(registry._PACKAGE, "recorder", lambda: recorder)
    monkeypatch.setattr(settings, "AGENT_7_IMPL", "recorder")
    return recorder


async def ready(
    client: AsyncClient, session: AsyncSession, policy: Policy, *, done: bool = True
) -> str:
    """一個待辦都完成的事件（平台才允許送件）。"""
    created = await client.post(
        f"/policies/{policy.id}/incidents", json={"description": "班機延誤了"}
    )
    incident_id = created.json()["incident"]["incident_id"]
    session.add(
        IncidentTodo(
            incident_id=incident_id,
            phase="after_return",
            title="準備文件",
            status="done" if done else "pending",
            done_by="user" if done else None,
            sort_order=0,
        )
    )
    await session.commit()
    return incident_id


FILLS = {"被保險人姓名": "王小明", "保單號碼": "A123456789"}


async def submissions(session: AsyncSession) -> list[PolicySubmission]:
    return list((await session.exec(select(PolicySubmission))).all())


async def is_completed(session: AsyncSession, incident_id: str) -> bool:
    session.expire_all()
    incident = await session.get(Incident, incident_id)
    assert incident is not None
    return incident.status == "completed"


async def test_send_puts_the_filled_values_into_the_letter_and_closes(
    client: AsyncClient, session: AsyncSession, policy: Policy, seven: Recorder
) -> None:
    i = await ready(client, session, policy)

    response = await client.post(
        f"/incidents/{i}/submission",
        json={"mode": "send", "fills": FILLS, "recipient": "claims@example.com"},
    )

    assert response.status_code == 201, response.text
    assert response.json()["status"] == "sent"
    [call] = seven.sent
    # 只換空格那一段，其他文字（保額等程式產生的內容）不動
    assert call["subject"] == "理賠申請：A123456789"
    assert call["body"] == "被保險人：王小明\n保單號碼：A123456789\n保額：6000000"
    assert call["recipient"] == "claims@example.com"
    assert call["mode"] == "send"
    [row] = await submissions(session)
    assert row.status == "sent"
    assert row.recipient == "claims@example.com"
    assert row.gmail_refs == [{"index": 0, "message_id": "msg-1"}]
    assert await is_completed(session, i)


@pytest.mark.parametrize(
    ("mode", "status", "url"),
    [
        ("send", "sent", "https://mail.google.com/mail/?authuser=a%40b.c#sent/msg-1"),
        (
            "draft",
            "drafted",
            "https://mail.google.com/mail/?authuser=a%40b.c#drafts?compose=m-9",
        ),
    ],
)
async def test_success_returns_the_subject_and_gmail_link(
    client: AsyncClient,
    session: AsyncSession,
    policy: Policy,
    seven: Recorder,
    mode: str,
    status: str,
    url: str,
) -> None:
    # 寄出或建立草稿後畫面告訴使用者是哪封信、給連結點開（主旨是填好空格的版本）
    i = await ready(client, session, policy)
    seven.result = SendResult(status=status, external_ref="x", gmail_url=url)  # pyright: ignore[reportArgumentType]

    response = await client.post(
        f"/incidents/{i}/submission",
        json={"mode": mode, "fills": FILLS, "recipient": "claims@example.com"},
    )

    assert response.status_code == 201, response.text
    assert response.json()["subject"] == "理賠申請：A123456789"
    assert response.json()["gmail_url"] == url


async def test_link_that_is_not_gmail_is_dropped(
    client: AsyncClient, session: AsyncSession, policy: Policy, seven: Recorder
) -> None:
    i = await ready(client, session, policy)
    seven.result = SendResult(
        status="sent", external_ref="msg-1", gmail_url="https://evil.example.com/"
    )

    response = await client.post(
        f"/incidents/{i}/submission",
        json={"mode": "send", "fills": FILLS, "recipient": "claims@example.com"},
    )

    assert response.status_code == 201, response.text
    assert response.json()["gmail_url"] is None


async def test_mode_defaults_to_send_for_the_old_request_shape(
    client: AsyncClient, session: AsyncSession, policy: Policy, seven: Recorder
) -> None:
    i = await ready(client, session, policy)

    # 舊的呼叫方式只有收件人：信裡還有空格，所以被擋；前端不會這樣呼叫了
    response = await client.post(
        f"/incidents/{i}/submission", json={"recipient": "claims@example.com"}
    )

    assert response.status_code == 409
    assert seven.sent == []


async def test_send_is_blocked_while_blanks_remain_and_lists_them(
    client: AsyncClient, session: AsyncSession, policy: Policy, seven: Recorder
) -> None:
    i = await ready(client, session, policy)

    response = await client.post(
        f"/incidents/{i}/submission",
        json={
            "fills": {"保單號碼": "A123456789"},
            "recipient": "claims@example.com",
        },
    )

    assert response.status_code == 409
    assert "被保險人姓名" in response.json()["detail"]
    assert "保單號碼" not in response.json()["detail"]
    assert seven.sent == []
    assert await submissions(session) == []
    assert not await is_completed(session, i)


async def test_blank_or_unknown_fills_do_not_count(
    client: AsyncClient, session: AsyncSession, policy: Policy, seven: Recorder
) -> None:
    i = await ready(client, session, policy)

    # 空白視同沒填；信上沒有的項目直接忽略，不回錯誤
    response = await client.post(
        f"/incidents/{i}/submission",
        json={
            "fills": {"被保險人姓名": "   ", "保單號碼": " A123 ", "不存在": "x"},
            "recipient": "claims@example.com",
        },
    )

    assert response.status_code == 409
    assert "被保險人姓名" in response.json()["detail"]
    # 值前後的空白會去掉（沒送出，但確認不會因為忽略項目而出錯）
    assert seven.sent == []


@pytest.mark.parametrize("recipient", [None, "", "不是信箱", "a@b"])
async def test_send_needs_a_valid_recipient(
    client: AsyncClient,
    session: AsyncSession,
    policy: Policy,
    seven: Recorder,
    recipient: str | None,
) -> None:
    i = await ready(client, session, policy)

    response = await client.post(
        f"/incidents/{i}/submission",
        json={"mode": "send", "fills": FILLS, "recipient": recipient},
    )

    assert response.status_code == 422
    assert seven.sent == []


async def test_draft_works_without_recipient_and_with_blanks_left(
    client: AsyncClient, session: AsyncSession, policy: Policy, seven: Recorder
) -> None:
    i = await ready(client, session, policy)
    seven.result = SendResult(status="drafted", external_ref="draft-9")

    response = await client.post(
        f"/incidents/{i}/submission",
        json={"mode": "draft", "fills": {"保單號碼": "A123456789"}},
    )

    assert response.status_code == 201, response.text
    assert response.json()["status"] == "drafted"
    [call] = seven.sent
    assert call["mode"] == "draft"
    assert call["recipient"] is None
    # 還沒填的空格保留，讓使用者到 Gmail 補
    assert "（請填寫被保險人姓名）" in call["body"]
    assert "A123456789" in call["body"]
    [row] = await submissions(session)
    assert row.status == "drafted"
    assert row.gmail_refs == [{"index": 0, "draft_id": "draft-9"}]
    assert await is_completed(session, i)


async def test_self_does_not_call_seven_and_closes(
    client: AsyncClient, session: AsyncSession, policy: Policy, seven: Recorder
) -> None:
    i = await ready(client, session, policy)

    response = await client.post(f"/incidents/{i}/submission", json={"mode": "self"})

    assert response.status_code == 201, response.text
    assert response.json()["status"] == "self_submitted"
    assert seven.sent == []
    [row] = await submissions(session)
    assert row.status == "self_submitted"
    assert row.recipient is None
    assert await is_completed(session, i)


@pytest.mark.parametrize("mode", ["send", "draft", "self"])
async def test_unfinished_todos_block_every_mode(
    client: AsyncClient,
    session: AsyncSession,
    policy: Policy,
    seven: Recorder,
    mode: str,
) -> None:
    i = await ready(client, session, policy, done=False)

    response = await client.post(
        f"/incidents/{i}/submission",
        json={"mode": mode, "fills": FILLS, "recipient": "claims@example.com"},
    )

    assert response.status_code == 409
    assert seven.sent == []
    assert await submissions(session) == []


async def test_failed_result_keeps_the_incident_open(
    client: AsyncClient, session: AsyncSession, policy: Policy, seven: Recorder
) -> None:
    i = await ready(client, session, policy)
    seven.result = SendResult(status="failed", reason="請先授權 Gmail，才能送件")

    response = await client.post(
        f"/incidents/{i}/submission",
        json={"fills": FILLS, "recipient": "claims@example.com"},
    )

    assert response.status_code == 201
    assert response.json()["status"] == "failed"
    assert response.json()["reason"] == "請先授權 Gmail，才能送件"
    [row] = await submissions(session)
    assert row.status == "pending"
    assert not await is_completed(session, i)


async def test_closed_incident_cannot_be_submitted_again(
    client: AsyncClient, session: AsyncSession, policy: Policy, seven: Recorder
) -> None:
    i = await ready(client, session, policy)
    body = {"fills": FILLS, "recipient": "claims@example.com"}
    assert (
        await client.post(f"/incidents/{i}/submission", json=body)
    ).status_code == 201

    again = await client.post(f"/incidents/{i}/submission", json=body)

    assert again.status_code == 409
    assert len(seven.sent) == 1


@pytest.mark.parametrize(
    ("fills", "problem"),
    [
        ({"被保險人姓名": "王小明1"}, "被保險人姓名"),
        ({"聯絡電話": "12345"}, "聯絡電話"),
    ],
)
@pytest.mark.parametrize("mode", ["send", "draft"])
async def test_bad_name_or_phone_is_rejected_with_422(
    client: AsyncClient,
    session: AsyncSession,
    policy: Policy,
    seven: Recorder,
    fills: dict[str, str],
    problem: str,
    mode: str,
) -> None:
    i = await ready(client, session, policy)

    response = await client.post(
        f"/incidents/{i}/submission",
        json={"mode": mode, "fills": {**FILLS, **fills}, "recipient": "a@b.co"},
    )

    assert response.status_code == 422
    assert problem in response.text
    assert seven.sent == []
    assert not await is_completed(session, i)


@pytest.mark.parametrize(
    ("result", "status", "url"),
    [
        (
            SendResult(status="sent", external_ref="msg-1", message_id="msg-1"),
            "sent",
            "https://mail.google.com/mail/?authuser={email}#sent/msg-1",
        ),
        (
            SendResult(status="drafted", external_ref="r-1", message_id="m-9"),
            "drafted",
            "https://mail.google.com/mail/?authuser={email}#drafts?compose=m-9",
        ),
        (
            SendResult(status="drafted", external_ref="r-1"),
            "drafted",
            None,
        ),
    ],
    ids=["寄出", "草稿", "草稿沒有信件編號"],
)
async def test_incident_page_gets_how_it_was_closed_and_the_gmail_link(
    client: AsyncClient,
    session: AsyncSession,
    policy: Policy,
    seven: Recorder,
    result: SendResult,
    status: str,
    url: str | None,
) -> None:
    from urllib.parse import quote

    from app.models import User

    i = await ready(client, session, policy)
    assert (await client.get(f"/incidents/{i}/submission")).json() == {
        "status": None,
        "gmail_url": None,
    }
    seven.result = result
    mode = "send" if status == "sent" else "draft"
    await client.post(
        f"/incidents/{i}/submission",
        json={"mode": mode, "fills": FILLS, "recipient": "claims@example.com"},
    )
    user = await session.get(User, policy.user_id)
    assert user is not None

    response = await client.get(f"/incidents/{i}/submission")

    assert response.status_code == 200, response.text
    expected = url.format(email=quote(user.email, safe="")) if url else None
    assert response.json() == {"status": status, "gmail_url": expected}
    [row] = await submissions(session)
    assert str(row.incident_id) == i


@pytest.mark.usefixtures("seven")
async def test_self_submitted_has_no_gmail_link(
    client: AsyncClient, session: AsyncSession, policy: Policy
) -> None:
    i = await ready(client, session, policy)
    await client.post(f"/incidents/{i}/submission", json={"mode": "self"})

    response = await client.get(f"/incidents/{i}/submission")

    assert response.json() == {"status": "self_submitted", "gmail_url": None}


async def test_failed_send_is_not_shown_as_closed(
    client: AsyncClient, session: AsyncSession, policy: Policy, seven: Recorder
) -> None:
    i = await ready(client, session, policy)
    seven.result = SendResult(status="failed", reason="請先授權 Gmail，才能送件")
    await client.post(
        f"/incidents/{i}/submission",
        json={"mode": "send", "fills": FILLS, "recipient": "claims@example.com"},
    )

    response = await client.get(f"/incidents/{i}/submission")

    assert response.json() == {"status": None, "gmail_url": None}
