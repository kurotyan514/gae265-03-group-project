"""授權 Drive、Gmail（ADR-0020）：導向 Google、callback 的授權分支、加密保存、Drive 資料夾。

用假的 Google 用戶端（fixture 在 conftest.py），不連 Google。
"""

import pytest
from app.core.google_oauth import DRIVE_SCOPE, GMAIL_SCOPE, GoogleOAuthError
from app.core.token_cipher import CURRENT_KEY_VERSION, cipher_from_settings
from app.models import GoogleGrant
from httpx import AsyncClient
from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from tests.google_support import (
    CALLBACK_URI,
    FakeGoogleOAuthClient,
    google_redirects_back,
    google_tokens,
    log_in_with_google,
    query,
    start_google,
)

LOGIN = ("openid", "email", "profile")


async def start_authorize(
    client: AsyncClient, purpose: str = "drive", next_path: str = "/dev/incident"
) -> str:
    """按「選擇檔案」或「送出」並同意用途說明：回傳這次的 state。"""
    return await start_google(
        client, "/auth/google/authorize", purpose=purpose, next=next_path
    )


async def grants(session: AsyncSession) -> list[GoogleGrant]:
    session.expire_all()
    return list((await session.exec(select(GoogleGrant))).all())


async def grant_count(session: AsyncSession) -> int:
    return (await session.exec(select(func.count()).select_from(GoogleGrant))).one()


# ---- 導向 Google ----


async def test_authorize_requires_login(client: AsyncClient) -> None:
    response = await client.get("/auth/google/authorize", params={"purpose": "drive"})
    assert response.status_code == 401


async def test_unknown_purpose_is_rejected(
    client: AsyncClient, fake_google: FakeGoogleOAuthClient
) -> None:
    await log_in_with_google(client, fake_google)
    response = await client.get("/auth/google/authorize", params={"purpose": "photos"})
    assert response.status_code == 422


async def test_dev_login_users_cannot_authorize(client: AsyncClient) -> None:
    await client.post("/auth/dev-login", json={"email": "dev@example.com"})
    response = await client.get(
        "/auth/google/authorize", params={"purpose": "drive", "next": "/dev/incident"}
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/dev/incident?google_auth=not_google_login"


@pytest.mark.parametrize(
    ("purpose", "scope"), [("drive", DRIVE_SCOPE), ("gmail", GMAIL_SCOPE)]
)
async def test_authorize_asks_google_for_the_logged_in_account(
    client: AsyncClient, fake_google: FakeGoogleOAuthClient, purpose: str, scope: str
) -> None:
    await log_in_with_google(client, fake_google, email="carol@example.com")
    response = await client.get("/auth/google/authorize", params={"purpose": purpose})
    assert response.status_code == 302
    q = query(response.headers["location"])
    assert q["scope"] == f"openid {scope}"
    assert q["login_hint"] == "carol@example.com"
    assert q["access_type"] == "offline"
    assert q["include_granted_scopes"] == "true"
    assert q["prompt"] == "consent"
    assert q["redirect_uri"] == CALLBACK_URI


# ---- 成功 ----


async def test_drive_grant_is_saved_encrypted_and_a_folder_is_created(
    client: AsyncClient, fake_google: FakeGoogleOAuthClient, session: AsyncSession
) -> None:
    await log_in_with_google(client, fake_google, sub="sub-1")
    state = await start_authorize(client, "drive", "/dev/incident?step=6")
    fake_google.tokens = google_tokens(
        sub="sub-1", scopes=(*LOGIN, DRIVE_SCOPE), refresh_token="rt-secret"
    )

    location = await google_redirects_back(client, state)

    assert location == "/dev/incident?step=6&google_auth=granted"
    [grant] = await grants(session)
    assert grant.status == "active"
    assert DRIVE_SCOPE in grant.scopes
    assert grant.refresh_token_encrypted is not None
    assert b"rt-secret" not in grant.refresh_token_encrypted
    assert cipher_from_settings().decrypt(grant.refresh_token_encrypted) == "rt-secret"
    assert grant.key_version == CURRENT_KEY_VERSION
    assert grant.drive_folder_id == "folder-1"
    assert fake_google.folders == ["好險有你 理賠文件"]
    assert (await client.get("/auth/me")).status_code == 200  # 授權不會登出


async def test_gmail_after_drive_keeps_one_grant_and_one_folder(
    client: AsyncClient, fake_google: FakeGoogleOAuthClient, session: AsyncSession
) -> None:
    await log_in_with_google(client, fake_google, sub="sub-1")
    state = await start_authorize(client, "drive")
    fake_google.tokens = google_tokens(
        sub="sub-1", scopes=(*LOGIN, DRIVE_SCOPE), refresh_token="rt-1"
    )
    await google_redirects_back(client, state)

    state = await start_authorize(client, "gmail")
    # include_granted_scopes：Google 回傳的 scope 包含之前授權過的
    fake_google.tokens = google_tokens(
        sub="sub-1", scopes=(*LOGIN, DRIVE_SCOPE, GMAIL_SCOPE), refresh_token="rt-2"
    )
    assert (await google_redirects_back(client, state)).endswith("google_auth=granted")

    [grant] = await grants(session)
    assert {DRIVE_SCOPE, GMAIL_SCOPE} <= set(grant.scopes)
    assert grant.refresh_token_encrypted is not None
    assert cipher_from_settings().decrypt(grant.refresh_token_encrypted) == "rt-2"
    assert fake_google.folders == ["好險有你 理賠文件"]  # 資料夾只建一次


async def test_gmail_only_grant_creates_no_drive_folder(
    client: AsyncClient, fake_google: FakeGoogleOAuthClient, session: AsyncSession
) -> None:
    # 沒上傳過文件、直接走到「送出」：第一次就只授權 Gmail
    await log_in_with_google(client, fake_google, sub="sub-1")
    state = await start_authorize(client, "gmail")
    fake_google.tokens = google_tokens(
        sub="sub-1", scopes=(*LOGIN, GMAIL_SCOPE), refresh_token="rt-gmail"
    )

    assert (await google_redirects_back(client, state)).endswith("google_auth=granted")
    [grant] = await grants(session)
    assert GMAIL_SCOPE in grant.scopes
    assert DRIVE_SCOPE not in grant.scopes
    assert grant.drive_folder_id is None
    assert fake_google.folders == []  # 只授權 Gmail 不會去 Drive 建資料夾


async def test_drive_after_gmail_creates_the_folder_then(
    client: AsyncClient, fake_google: FakeGoogleOAuthClient, session: AsyncSession
) -> None:
    await log_in_with_google(client, fake_google, sub="sub-1")
    state = await start_authorize(client, "gmail")
    fake_google.tokens = google_tokens(
        sub="sub-1", scopes=(*LOGIN, GMAIL_SCOPE), refresh_token="rt-1"
    )
    await google_redirects_back(client, state)

    state = await start_authorize(client, "drive")
    fake_google.tokens = google_tokens(
        sub="sub-1", scopes=(*LOGIN, GMAIL_SCOPE, DRIVE_SCOPE), refresh_token="rt-2"
    )
    assert (await google_redirects_back(client, state)).endswith("google_auth=granted")

    [grant] = await grants(session)
    assert {DRIVE_SCOPE, GMAIL_SCOPE} <= set(grant.scopes)
    assert grant.drive_folder_id == "folder-1"
    assert fake_google.folders == ["好險有你 理賠文件"]


# ---- 失敗 ----


async def test_another_google_account_is_rejected_and_nothing_is_saved(
    client: AsyncClient, fake_google: FakeGoogleOAuthClient, session: AsyncSession
) -> None:
    await log_in_with_google(
        client, fake_google, sub="sub-1", email="carol@example.com"
    )
    state = await start_authorize(client)
    fake_google.tokens = google_tokens(
        sub="someone-else", scopes=(*LOGIN, DRIVE_SCOPE), refresh_token="rt"
    )

    assert (await google_redirects_back(client, state)).endswith(
        "google_auth=account_mismatch"
    )
    assert await grant_count(session) == 0
    assert fake_google.folders == []
    me = (await client.get("/auth/me")).json()
    assert me["email"] == "carol@example.com"  # 還是原本的使用者


async def test_missing_permission_counts_as_cancelled(
    client: AsyncClient, fake_google: FakeGoogleOAuthClient, session: AsyncSession
) -> None:
    await log_in_with_google(client, fake_google, sub="sub-1")
    state = await start_authorize(client, "gmail")
    # Google 回來時沒有 Gmail 的權限：對使用者來說就是沒有同意
    fake_google.tokens = google_tokens(sub="sub-1", scopes=LOGIN, refresh_token="rt")

    assert (await google_redirects_back(client, state)).endswith(
        "google_auth=cancelled"
    )
    [grant] = await grants(session)
    assert GMAIL_SCOPE not in grant.scopes  # 只記實際拿到的


async def test_only_openid_without_refresh_token_counts_as_cancelled(
    client: AsyncClient, fake_google: FakeGoogleOAuthClient, session: AsyncSession
) -> None:
    # 實測：Google 有時只給 openid，沒有 refresh token，id_token 裡也沒有 email。
    # 要回報「取消」，不是「Google 暫時失敗」
    await log_in_with_google(client, fake_google, sub="sub-1")
    state = await start_authorize(client, "drive")
    fake_google.tokens = google_tokens(
        sub="sub-1", email=None, scopes=("openid",), refresh_token=None
    )

    assert (await google_redirects_back(client, state)).endswith(
        "google_auth=cancelled"
    )
    assert await grant_count(session) == 0


async def test_cancelling_at_google_saves_nothing(
    client: AsyncClient, fake_google: FakeGoogleOAuthClient, session: AsyncSession
) -> None:
    await log_in_with_google(client, fake_google)
    state = await start_authorize(client)
    location = await google_redirects_back(client, state, error="access_denied")
    assert location.endswith("google_auth=cancelled")
    assert await grant_count(session) == 0


async def test_google_failure_saves_nothing_and_keeps_the_login(
    client: AsyncClient, fake_google: FakeGoogleOAuthClient, session: AsyncSession
) -> None:
    await log_in_with_google(client, fake_google)
    state = await start_authorize(client)
    fake_google.exchange_error = GoogleOAuthError("Google 回應 500")

    assert (await google_redirects_back(client, state)).endswith(
        "google_auth=google_failed"
    )
    assert await grant_count(session) == 0
    assert (await client.get("/auth/me")).status_code == 200


async def test_missing_refresh_token_is_reported(
    client: AsyncClient, fake_google: FakeGoogleOAuthClient, session: AsyncSession
) -> None:
    await log_in_with_google(client, fake_google, sub="sub-1")
    state = await start_authorize(client)
    fake_google.tokens = google_tokens(
        sub="sub-1", scopes=(*LOGIN, DRIVE_SCOPE), refresh_token=None
    )
    assert (await google_redirects_back(client, state)).endswith(
        "google_auth=google_failed"
    )
    assert await grant_count(session) == 0


async def test_wrong_state_is_rejected_and_keeps_the_login(
    client: AsyncClient, fake_google: FakeGoogleOAuthClient, session: AsyncSession
) -> None:
    await log_in_with_google(client, fake_google)
    await start_authorize(client, "drive", "/dev/incident")
    fake_google.tokens = google_tokens(scopes=(*LOGIN, DRIVE_SCOPE), refresh_token="rt")

    location = await google_redirects_back(client, "forged-state")

    assert location == "/dev/incident?google_auth=state_mismatch"
    assert await grant_count(session) == 0
    assert (await client.get("/auth/me")).status_code == 200


async def test_folder_failure_keeps_the_grant_and_retries_next_time(
    client: AsyncClient, fake_google: FakeGoogleOAuthClient, session: AsyncSession
) -> None:
    await log_in_with_google(client, fake_google, sub="sub-1")

    fake_google.folder_error = GoogleOAuthError("Google 回應 500")
    state = await start_authorize(client)
    fake_google.tokens = google_tokens(
        sub="sub-1", scopes=(*LOGIN, DRIVE_SCOPE), refresh_token="rt"
    )
    assert (await google_redirects_back(client, state)).endswith(
        "google_auth=google_failed"
    )
    [grant] = await grants(session)
    assert grant.drive_folder_id is None

    fake_google.folder_error = None
    state = await start_authorize(client)
    assert (await google_redirects_back(client, state)).endswith("google_auth=granted")
    [grant] = await grants(session)
    assert grant.drive_folder_id == "folder-1"
