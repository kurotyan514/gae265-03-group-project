"""7 號 agent 的 send：用使用者的 Gmail 寄出送件包（規格：docs/specs/agent-7-package.md）。

直接呼叫 send，授權用假的，不連 Google。
"""

import uuid

from app.agents.package import GmailClaimPackager
from app.contracts import (
    ClaimPackage,
    IncidentContext,
    PolicySummary,
    UserContext,
)

USER = UserContext(user_id=uuid.uuid4(), email="owner@example.com")


class FakeGoogleAccess:
    """只回給定權限的 token；其他權限回 None（沒授權、已撤銷、過期都是 None）。"""

    def __init__(self, *granted: str) -> None:
        self.granted = set(granted)
        self.asked: list[str] = []

    async def access_token(self, user: UserContext, scope: str) -> str | None:
        self.asked.append(scope)
        return f"token-{scope}" if scope in self.granted else None

    async def drive_folder_id(self, user: UserContext) -> str | None:
        return "folder-id" if "drive.file" in self.granted else None


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


async def _send(google: FakeGoogleAccess):
    ctx = _ctx()
    package = await GmailClaimPackager().build(ctx)
    assert isinstance(package, ClaimPackage)
    return await GmailClaimPackager().send(
        ctx, package, "claims@example.com", USER, google
    )


async def test_沒有Gmail授權時回failed並說明請先授權Gmail() -> None:
    # 交接說明規則 3：沒有授權時回 failed、說明請先授權，不丟例外、不寄出
    result = await _send(FakeGoogleAccess("drive.file"))

    assert result.status == "failed"
    assert result.external_ref is None
    assert result.reason and "請先授權" in result.reason and "Gmail" in result.reason
    assert "Drive" not in result.reason


async def test_沒有Drive授權時回failed並說明請先授權Drive() -> None:
    # 寄信要從使用者的 Drive 取附件，所以 Drive 也要授權（ADR-0020）
    result = await _send(FakeGoogleAccess("gmail.compose"))

    assert result.status == "failed"
    assert result.external_ref is None
    assert result.reason and "請先授權" in result.reason and "Drive" in result.reason
    assert "Gmail" not in result.reason


async def test_兩個都沒授權時一起說明() -> None:
    google = FakeGoogleAccess()

    result = await _send(google)

    assert result.status == "failed"
    assert result.reason and "Gmail" in result.reason and "Drive" in result.reason
    assert set(google.asked) == {"gmail.compose", "drive.file"}


async def test_建立草稿尚未接上時明確回failed_不碰Google授權() -> None:
    # 契約 v2.1 的 mode="draft" 等 #154 接上；在那之前明確回 failed，不寄也不建
    google = FakeGoogleAccess("gmail.compose", "drive.file")
    ctx = _ctx()
    package = await GmailClaimPackager().build(ctx)

    result = await GmailClaimPackager().send(
        ctx, package, None, USER, google, mode="draft"
    )

    assert result.status == "failed"
    assert result.reason and "開發中" in result.reason
    assert google.asked == []
