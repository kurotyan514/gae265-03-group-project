"""契約 v2.8：預覽與送件呼叫 7 號的 build 時帶上使用者與 Google 授權（#155 驗收 7-2）。

7 號用它確認附件還在不在 Drive；只收 ctx 的舊實作照樣能用（平台只對簽名有 google、user 的實作帶上）。
"""

import pytest
from app.agents import registry
from app.api.routes import incidents as incidents_route
from app.contracts import (
    ClaimPackage,
    GoogleAccess,
    IncidentContext,
    SendResult,
    UnavailableAttachment,
    UserContext,
)
from app.core.config import settings
from app.models import Policy
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from tests.contracts.test_submission import ready

pytestmark = pytest.mark.usefixtures("user")


class Granted:
    """平台給的 Google 授權（測試用）。"""

    async def access_token(self, user: UserContext, scope: str) -> str | None:
        return f"token-{scope}"

    async def drive_folder_id(self, user: UserContext) -> str | None:
        return "folder"


GRANTED = Granted()


class NewPackager:
    """v2.8 的 7 號：build 收 google、user，記下收到什麼。"""

    def __init__(self) -> None:
        self.builds: list[tuple[GoogleAccess | None, UserContext | None]] = []
        self.sent: list[ClaimPackage] = []

    async def build(
        self,
        ctx: IncidentContext,
        google: GoogleAccess | None = None,
        user: UserContext | None = None,
    ) -> ClaimPackage:
        self.builds.append((google, user))
        # 固定回一個取不到的附件，檢查這個欄位能原樣傳到前端
        return ClaimPackage(
            subject="理賠申請",
            body="內文",
            unavailable_attachments=[
                UnavailableAttachment(
                    document_id=ctx.incident_id,
                    file_name="班機延誤_機票及登機證_1.pdf",
                    reason="trashed",
                )
            ],
        )

    async def send(
        self,
        ctx: IncidentContext,
        package: ClaimPackage,
        recipient: str | None,
        user: UserContext,
        google: GoogleAccess,
        mode: str = "send",
    ) -> SendResult:
        self.sent.append(package)
        return SendResult(status="sent", external_ref="msg-1")


class OldPackager:
    """v2.3 以前的 7 號：build 只收 ctx。"""

    async def build(self, ctx: IncidentContext) -> ClaimPackage:
        return ClaimPackage(subject="理賠申請", body="內文")

    async def send(
        self,
        ctx: IncidentContext,
        package: ClaimPackage,
        recipient: str | None,
        user: UserContext,
        google: GoogleAccess,
    ) -> SendResult:
        return SendResult(status="sent", external_ref="msg-1")


def _use(monkeypatch: pytest.MonkeyPatch, packager: object) -> None:
    monkeypatch.setitem(registry._PACKAGE, "under-test", lambda: packager)
    monkeypatch.setattr(settings, "AGENT_7_IMPL", "under-test")
    monkeypatch.setattr(incidents_route, "get_google_access", lambda: GRANTED)


async def test_preview_passes_the_user_and_google_access_to_build(
    client: AsyncClient,
    session: AsyncSession,
    policy: Policy,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seven = NewPackager()
    _use(monkeypatch, seven)
    i = await ready(client, session, policy)

    response = await client.get(f"/incidents/{i}/package")

    assert response.status_code == 200, response.text
    [(google, user)] = seven.builds
    assert google is GRANTED
    assert user is not None and user.email == "owner@example.com"
    # 取不到的附件原樣交給前端提示使用者
    [unavailable] = response.json()["unavailable_attachments"]
    assert unavailable["file_name"] == "班機延誤_機票及登機證_1.pdf"
    assert unavailable["reason"] == "trashed"


async def test_submission_builds_the_same_way_as_the_preview(
    client: AsyncClient,
    session: AsyncSession,
    policy: Policy,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 送件時重新 build，也要帶上授權：取不到的附件在這裡就排除，寄出的信與預覽一致
    seven = NewPackager()
    _use(monkeypatch, seven)
    i = await ready(client, session, policy)

    response = await client.post(
        f"/incidents/{i}/submission",
        json={"mode": "send", "fills": {}, "recipient": "claims@example.com"},
    )

    assert response.status_code == 201, response.text
    [(google, user)] = seven.builds
    assert google is GRANTED and user is not None


async def test_an_old_packager_that_only_takes_ctx_still_works(
    client: AsyncClient,
    session: AsyncSession,
    policy: Policy,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use(monkeypatch, OldPackager())
    i = await ready(client, session, policy)

    preview = await client.get(f"/incidents/{i}/package")
    sent = await client.post(
        f"/incidents/{i}/submission",
        json={"mode": "send", "fills": {}, "recipient": "claims@example.com"},
    )

    assert preview.status_code == 200, preview.text
    assert preview.json()["unavailable_attachments"] == []
    assert sent.status_code == 201, sent.text
    assert sent.json()["status"] == "sent"
