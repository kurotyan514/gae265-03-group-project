"""查詢與取消 Google 授權（ADR-0020）：狀態會實際向 Google 確認、取消後清空 token 但保留紀錄。

用假的 Google 用戶端（fixture 在 conftest.py），不連 Google。
"""

from app.core.google_oauth import (
    DRIVE_SCOPE,
    GMAIL_SCOPE,
    GoogleOAuthError,
    InvalidGrantError,
)
from app.models import GoogleGrant
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from tests.google_support import (
    FakeGoogleOAuthClient,
    authorize_with_google,
    log_in_with_google,
)

LOGIN = ("openid", "email", "profile")


async def only_grant(session: AsyncSession) -> GoogleGrant:
    session.expire_all()
    return (await session.exec(select(GoogleGrant))).one()


async def drive_granted(client: AsyncClient, fake: FakeGoogleOAuthClient) -> None:
    await log_in_with_google(client, fake)
    location = await authorize_with_google(
        client, fake, scopes=(*LOGIN, DRIVE_SCOPE), refresh_token="rt-1"
    )
    assert location.endswith("google_auth=granted")


# ---- 查詢狀態 ----


async def test_status_requires_login(client: AsyncClient) -> None:
    assert (await client.get("/auth/google/grant")).status_code == 401


async def test_status_without_any_grant(
    client: AsyncClient, fake_google: FakeGoogleOAuthClient
) -> None:
    await log_in_with_google(client, fake_google)
    assert (await client.get("/auth/google/grant")).json() == {
        "status": "none",
        "drive": False,
        "gmail": False,
    }


async def test_dev_login_user_has_no_grant(client: AsyncClient) -> None:
    await client.post("/auth/dev-login", json={"email": "dev@example.com"})
    assert (await client.get("/auth/google/grant")).json()["status"] == "none"


async def test_status_checks_with_google_and_reports_each_permission(
    client: AsyncClient, fake_google: FakeGoogleOAuthClient, session: AsyncSession
) -> None:
    await drive_granted(client, fake_google)

    assert (await client.get("/auth/google/grant")).json() == {
        "status": "active",
        "drive": True,
        "gmail": False,
    }
    assert fake_google.refreshed == ["rt-1"]  # 用解密後的 refresh token 向 Google 確認
    assert (await only_grant(session)).last_refreshed_at is not None


async def test_status_with_only_gmail(
    client: AsyncClient, fake_google: FakeGoogleOAuthClient
) -> None:
    await log_in_with_google(client, fake_google)
    await authorize_with_google(
        client, fake_google, purpose="gmail", scopes=(*LOGIN, GMAIL_SCOPE)
    )

    assert (await client.get("/auth/google/grant")).json() == {
        "status": "active",
        "drive": False,
        "gmail": True,
    }


async def test_expired_grant_is_marked_invalid(
    client: AsyncClient, fake_google: FakeGoogleOAuthClient, session: AsyncSession
) -> None:
    await drive_granted(client, fake_google)
    fake_google.refresh_results["rt-1"] = InvalidGrantError("refresh token 已失效")

    assert (await client.get("/auth/google/grant")).json() == {
        "status": "invalid",
        "drive": False,
        "gmail": False,
    }
    assert (await only_grant(session)).status == "invalid"


async def test_google_being_down_does_not_mark_the_grant_invalid(
    client: AsyncClient, fake_google: FakeGoogleOAuthClient, session: AsyncSession
) -> None:
    await drive_granted(client, fake_google)
    fake_google.refresh_results["rt-1"] = GoogleOAuthError("Google 回應 503")

    body = (await client.get("/auth/google/grant")).json()
    assert body["status"] == "active"
    assert body["drive"] is True
    assert (await only_grant(session)).status == "active"


async def test_reauthorizing_after_expiry_makes_it_active_again(
    client: AsyncClient, fake_google: FakeGoogleOAuthClient
) -> None:
    await drive_granted(client, fake_google)
    fake_google.refresh_results["rt-1"] = InvalidGrantError("refresh token 已失效")
    await client.get("/auth/google/grant")

    await authorize_with_google(
        client, fake_google, scopes=(*LOGIN, DRIVE_SCOPE), refresh_token="rt-2"
    )
    assert (await client.get("/auth/google/grant")).json()["status"] == "active"


# ---- 取消授權 ----


async def test_revoke_requires_login(client: AsyncClient) -> None:
    assert (await client.post("/auth/google/revoke")).status_code == 401


async def test_revoke_tells_google_clears_the_token_and_keeps_the_record(
    client: AsyncClient, fake_google: FakeGoogleOAuthClient, session: AsyncSession
) -> None:
    await drive_granted(client, fake_google)

    assert (await client.post("/auth/google/revoke")).status_code == 204

    assert fake_google.revoked == ["rt-1"]
    grant = await only_grant(session)  # 紀錄還在
    assert grant.refresh_token_encrypted is None
    assert grant.status == "revoked"
    assert grant.revoked_at is not None
    assert grant.drive_folder_id is not None  # 使用者 Drive 裡的資料夾不動

    fake_google.refreshed.clear()
    assert (await client.get("/auth/google/grant")).json() == {
        "status": "revoked",
        "drive": False,
        "gmail": False,
    }
    assert fake_google.refreshed == []  # 已取消就不再問 Google
    assert (await client.get("/auth/me")).status_code == 200  # 取消授權不是登出


async def test_revoke_still_clears_the_token_when_google_fails(
    client: AsyncClient, fake_google: FakeGoogleOAuthClient, session: AsyncSession
) -> None:
    await drive_granted(client, fake_google)
    fake_google.revoke_error = GoogleOAuthError("Google 回應 503")

    assert (await client.post("/auth/google/revoke")).status_code == 204
    grant = await only_grant(session)
    assert grant.refresh_token_encrypted is None
    assert grant.status == "revoked"


async def test_revoke_without_a_grant_is_fine(
    client: AsyncClient, fake_google: FakeGoogleOAuthClient
) -> None:
    await log_in_with_google(client, fake_google)
    assert (await client.post("/auth/google/revoke")).status_code == 204
    assert fake_google.revoked == []


async def test_authorizing_again_after_revoke_reactivates_the_same_record(
    client: AsyncClient, fake_google: FakeGoogleOAuthClient, session: AsyncSession
) -> None:
    await drive_granted(client, fake_google)
    await client.post("/auth/google/revoke")
    revoked_id = (await only_grant(session)).id

    await authorize_with_google(
        client,
        fake_google,
        scopes=(*LOGIN, DRIVE_SCOPE, GMAIL_SCOPE),
        refresh_token="rt-2",
    )

    grant = await only_grant(session)
    assert grant.id == revoked_id
    assert grant.status == "active"
    assert grant.revoked_at is None
    assert (await client.get("/auth/google/grant")).json() == {
        "status": "active",
        "drive": True,
        "gmail": True,
    }
