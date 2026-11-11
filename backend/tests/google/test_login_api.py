"""Google 登入（ADR-0020）：導向 Google、callback、state、email 驗證、next。

用假的 Google 用戶端（fixture 在 conftest.py），不連 Google。
"""

import pytest
from app.core.config import settings
from app.core.google_oauth import GoogleOAuthError
from app.models import Identity, User
from httpx import ASGITransport, AsyncClient
from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from tests.google_support import (
    CALLBACK_URI,
    FakeGoogleOAuthClient,
    google_redirects_back,
    google_tokens,
    query,
    start_google,
    use_google_settings,
)
from tests.test_auth_api import make_app


async def start_login(client: AsyncClient, next_path: str | None = None) -> str:
    """按「使用 Google 登入」：回傳這次的 state。"""
    params = {"next": next_path} if next_path is not None else {}
    return await start_google(client, "/auth/google/login", **params)


async def finish_login(client: AsyncClient, state: str, **extra: str) -> str:
    """Google 導回 callback：回傳被導到哪裡。"""
    return await google_redirects_back(client, state, **extra)


async def count(session: AsyncSession, model: type[User] | type[Identity]) -> int:
    return (await session.exec(select(func.count()).select_from(model))).one()


# ---- 導向 Google ----


async def test_login_redirects_to_google_for_basic_profile(client: AsyncClient) -> None:
    response = await client.get("/auth/google/login")
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("https://accounts.google.com/")
    q = query(location)
    assert q["scope"] == "openid email profile"
    assert q["prompt"] == "select_account"
    assert q["redirect_uri"] == CALLBACK_URI
    assert q["client_id"] == settings.GOOGLE_CLIENT_ID
    assert len(q["state"]) >= 32


async def test_each_login_gets_a_new_state(client: AsyncClient) -> None:
    assert await start_login(client) != await start_login(client)


async def test_google_login_is_unavailable_without_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 不換掉 Google 用戶端的依賴：由真的依賴判斷設定不完整
    use_google_settings(monkeypatch, GOOGLE_CLIENT_SECRET=None)
    async with AsyncClient(
        transport=ASGITransport(app=make_app()),
        base_url=f"http://test{settings.API_V1_STR}",
    ) as plain:
        assert (await plain.get("/auth/google/login")).status_code == 503


# ---- callback：成功 ----


async def test_callback_logs_in_a_new_user_and_returns_to_next(
    client: AsyncClient, fake_google: FakeGoogleOAuthClient, session: AsyncSession
) -> None:
    state = await start_login(client, "/plans?tab=2")
    fake_google.tokens = google_tokens(sub="sub-123", email="Carol@Example.com")

    assert await finish_login(client, state) == "/plans?tab=2"
    assert fake_google.exchanged == [("the-code", CALLBACK_URI)]

    me = await client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "carol@example.com"
    assert me.json()["name"] == "Carol"
    assert me.json()["login_provider"] == "google"

    identity = (await session.exec(select(Identity))).one()
    assert identity.provider == "google"
    assert identity.provider_user_id == "sub-123"
    assert identity.email_verified is True


async def test_logging_in_again_reuses_the_user_and_updates_the_email(
    client: AsyncClient, fake_google: FakeGoogleOAuthClient, session: AsyncSession
) -> None:
    fake_google.tokens = google_tokens(sub="sub-1", email="old@example.com")
    await finish_login(client, await start_login(client))
    first_id = (await client.get("/auth/me")).json()["id"]

    fake_google.tokens = google_tokens(sub="sub-1", email="new@example.com")
    await finish_login(client, await start_login(client))
    me = (await client.get("/auth/me")).json()

    assert me["id"] == first_id
    assert me["email"] == "new@example.com"
    assert await count(session, User) == 1


async def test_another_google_account_is_another_user(
    client: AsyncClient, fake_google: FakeGoogleOAuthClient, session: AsyncSession
) -> None:
    for sub in ("sub-a", "sub-b"):
        fake_google.tokens = google_tokens(sub=sub, email=f"{sub}@example.com")
        await finish_login(client, await start_login(client))
    assert await count(session, User) == 2


# ---- callback：失敗 ----


async def test_unverified_email_cannot_log_in(
    client: AsyncClient, fake_google: FakeGoogleOAuthClient, session: AsyncSession
) -> None:
    state = await start_login(client)
    fake_google.tokens = google_tokens(email_verified=False)

    assert await finish_login(client, state) == "/login?error=email_unverified"
    assert (await client.get("/auth/me")).status_code == 401
    assert await count(session, User) == 0


async def test_wrong_state_is_rejected_without_asking_google(
    client: AsyncClient, fake_google: FakeGoogleOAuthClient
) -> None:
    await start_login(client)
    fake_google.tokens = google_tokens()

    assert await finish_login(client, "forged-state") == "/login?error=state_mismatch"
    assert fake_google.exchanged == []
    assert (await client.get("/auth/me")).status_code == 401


async def test_callback_without_starting_login_is_rejected(
    client: AsyncClient, fake_google: FakeGoogleOAuthClient
) -> None:
    assert await finish_login(client, "any-state") == "/login?error=state_mismatch"
    assert fake_google.exchanged == []


async def test_a_state_can_only_be_used_once(
    client: AsyncClient, fake_google: FakeGoogleOAuthClient
) -> None:
    state = await start_login(client)
    fake_google.tokens = google_tokens()
    await finish_login(client, state)

    assert await finish_login(client, state) == "/login?error=state_mismatch"


async def test_cancelling_at_google_is_reported(
    client: AsyncClient, fake_google: FakeGoogleOAuthClient
) -> None:
    state = await start_login(client)
    location = await finish_login(client, state, error="access_denied")
    assert location == "/login?error=cancelled"
    assert fake_google.exchanged == []


async def test_google_failure_is_reported(
    client: AsyncClient, fake_google: FakeGoogleOAuthClient
) -> None:
    state = await start_login(client)
    fake_google.exchange_error = GoogleOAuthError("Google 回應 500")

    assert await finish_login(client, state) == "/login?error=google_failed"
    assert (await client.get("/auth/me")).status_code == 401


async def test_missing_email_cannot_log_in(
    client: AsyncClient, fake_google: FakeGoogleOAuthClient, session: AsyncSession
) -> None:
    state = await start_login(client)
    fake_google.tokens = google_tokens(email=None)
    assert await finish_login(client, state) == "/login?error=google_failed"
    assert await count(session, User) == 0


async def test_missing_identity_is_reported(
    client: AsyncClient, fake_google: FakeGoogleOAuthClient
) -> None:
    state = await start_login(client)
    fake_google.tokens = google_tokens(with_identity=False)
    assert await finish_login(client, state) == "/login?error=google_failed"


# ---- next 只接受站內路徑 ----


@pytest.mark.parametrize(
    "next_path",
    [
        "https://evil.example.com",
        "//evil.example.com",
        "/\\evil.example.com",
        "plans",
        "",
    ],
)
async def test_next_outside_the_site_falls_back_to_home(
    client: AsyncClient, fake_google: FakeGoogleOAuthClient, next_path: str
) -> None:
    state = await start_login(client, next_path)
    fake_google.tokens = google_tokens()
    assert await finish_login(client, state) == "/"
