"""7 號的離線版（gmail-offline）：只換掉連 Google 的部分，給契約測試與展示用（規格「模組」）。"""

import uuid

import pytest
from app.agents import registry
from app.agents.package import GmailClaimPackager
from app.agents.package.google_http import HttpGoogleApi
from app.contracts import (
    AttachmentRef,
    ClaimPackage,
    IncidentContext,
    PolicySummary,
    UserContext,
)
from app.core.config import settings

USER = UserContext(user_id=uuid.uuid4(), email="owner@example.com")


class FakeGoogleAccess:
    def __init__(self, *granted: str) -> None:
        self.granted = set(granted)

    async def access_token(self, user: UserContext, scope: str) -> str | None:
        return f"token-{scope}" if scope in self.granted else None

    async def drive_folder_id(self, user: UserContext) -> str | None:
        return None


def _ctx() -> IncidentContext:
    return IncidentContext(
        incident_id=uuid.uuid4(),
        title="班機延誤",
        description="班機延誤了六個小時",
        status="open",
        policy=PolicySummary(
            plan_id="fubon_advanced",
            plan_name="富邦國外旅平險-進階型",
            insurance_codes=[],
            coverages=[],
        ),
    )


PACKAGE = ClaimPackage(
    subject="旅遊保險理賠申請－富邦國外旅平險-進階型－2026/08/10～08/14",
    body="我是被保險人王小明…\n聯絡電話：0912345678",
    attachments=[
        AttachmentRef(
            document_id=uuid.uuid4(), file_name="a.pdf", storage_path="file-1"
        )
    ],
)


def _use(monkeypatch: pytest.MonkeyPatch, impl: str, environment: str) -> None:
    monkeypatch.setattr(settings, "AGENT_7_IMPL", impl)
    monkeypatch.setattr(settings, "ENVIRONMENT", environment)


async def test_離線版不連Google也能寄出(monkeypatch: pytest.MonkeyPatch) -> None:
    _use(monkeypatch, "gmail-offline", "test")
    packager = registry.get_claim_packager()

    result = await packager.send(
        _ctx(),
        PACKAGE,
        "claims@example.com",
        USER,
        FakeGoogleAccess("gmail.compose", "drive.file"),
    )

    assert isinstance(packager, GmailClaimPackager)
    assert result.status == "sent"
    assert result.external_ref and result.external_ref.startswith("offline-")


async def test_離線版的授權照平台給的判斷_沒授權一樣回failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use(monkeypatch, "gmail-offline", "test")

    result = await registry.get_claim_packager().send(
        _ctx(), PACKAGE, "claims@example.com", USER, FakeGoogleAccess()
    )

    assert result.status == "failed"
    assert result.reason and "請先授權" in result.reason


def test_離線版在正式環境拒絕運作(monkeypatch: pytest.MonkeyPatch) -> None:
    # .env 設錯時不能在正式網站「假裝寄出」（規格「模組」）
    _use(monkeypatch, "gmail-offline", "production")

    with pytest.raises(RuntimeError, match="gmail-offline"):
        registry.get_claim_packager()


def test_正式版用真的連Google的轉接器(monkeypatch: pytest.MonkeyPatch) -> None:
    _use(monkeypatch, "gmail", "production")

    packager = registry.get_claim_packager()

    assert isinstance(packager, GmailClaimPackager)
    assert isinstance(packager.google_api, HttpGoogleApi)
