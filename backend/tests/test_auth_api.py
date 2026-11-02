"""使用者登入（ADR-0008）：Google callback、白名單、dev-login、session 與 current_user。
Google 本身不連：authorize_access_token／authorize_redirect 換成假的。"""

from collections.abc import AsyncGenerator
from typing import Any

import pytest
from app.api.main import build_api_router
from app.core.auth import is_email_allowed, oauth, safe_next_path
from app.core.config import Settings, settings
from app.core.db import get_session
from app.models import User
from authlib.integrations.starlette_client import OAuthError
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel import func
from sqlmodel import select as sm_select
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.middleware.sessions import SessionMiddleware

USERINFO = {
    "sub": "google-sub-1",
    "email": "Alice@Example.com",
    "email_verified": True,
    "name": "Alice",
}


def make_settings(**kw: Any) -> Settings:
    """不讀 .env 的 Settings，測試才不受開發者本機設定影響。"""
    return Settings(_env_file=None, **kw)  # pyright: ignore[reportCallIssue]


def make_app(environment: str = "local", dev_login: bool = True) -> FastAPI:
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret", same_site="lax")
    app.include_router(
        build_api_router(environment, dev_login), prefix=settings.API_V1_STR
    )
    return app


@pytest.fixture
async def auth_client(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[AsyncClient]:
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", SecretStr("test-secret"))
    app = make_app()

    async def override_get_session() -> AsyncGenerator[AsyncSession]:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=f"http://test{settings.API_V1_STR}"
    ) as client:
        yield client


def fake_google(
    monkeypatch: pytest.MonkeyPatch, userinfo: dict[str, Any] | None = USERINFO
) -> dict[str, Any]:
    """把 Google 換成假的；回傳的 dict 會記下 authorize_redirect 收到的 redirect_uri。"""
    seen: dict[str, Any] = {}

    async def authorize_redirect(_request: Any, redirect_uri: str) -> RedirectResponse:
        seen["redirect_uri"] = redirect_uri
        return RedirectResponse("https://accounts.google.test/auth")

    async def authorize_access_token(_request: Any) -> dict[str, Any]:
        return {"userinfo": userinfo}

    monkeypatch.setattr(oauth.google, "authorize_redirect", authorize_redirect)
    monkeypatch.setattr(oauth.google, "authorize_access_token", authorize_access_token)
    return seen


async def user_count(session: AsyncSession) -> int:
    return (await session.exec(sm_select(func.count()).select_from(User))).one()


# ---- 不需要 Google 的純邏輯 ----


@pytest.mark.parametrize(
    ("allowed", "email", "expected"),
    [
        ("", "anyone@example.com", True),  # 留空＝不限
        ("a@example.com,b@example.com", "b@example.com", True),
        ("a@example.com, B@Example.com", "b@example.COM", True),  # 不分大小寫、容許空白
        ("a@example.com", "c@example.com", False),
        (" , ", "anyone@example.com", True),  # 只有分隔符號也算留空
    ],
)
def test_allowlist(allowed: str, email: str, expected: bool) -> None:
    s = make_settings(ALLOWED_EMAILS=allowed)
    assert is_email_allowed(email, s) is expected


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("/policies", "/policies"),
        ("/policies?id=1", "/policies?id=1"),
        (None, "/account"),
        ("", "/account"),
        ("https://evil.example.com", "/account"),
        ("//evil.example.com", "/account"),
        ("/\\evil.example.com", "/account"),
        ("policies", "/account"),
    ],
)
def test_next_path_only_allows_paths_on_this_site(
    given: str | None, expected: str
) -> None:
    assert safe_next_path(given) == expected


def test_dev_login_never_works_in_production() -> None:
    def enabled(environment: str, flag: bool) -> bool:
        return make_settings(
            ENVIRONMENT=environment, DEV_LOGIN_ENABLED=flag
        ).dev_login_enabled

    assert enabled("local", True)
    assert not enabled("local", False)  # 沒明確打開就是關的
    assert not enabled("production", True)


def paths(environment: str, dev_login: bool) -> set[str]:
    return set(make_app(environment, dev_login).openapi()["paths"])


def test_dev_login_route_is_only_registered_when_allowed() -> None:
    route = f"{settings.API_V1_STR}/auth/dev-login"
    assert route in paths("local", True)
    assert route not in paths("local", False)
    assert route not in paths("production", True)  # 就算旗標打開，正式環境也不註冊


def test_production_requires_login_settings() -> None:
    def check(**kw: Any) -> None:
        make_settings(ENVIRONMENT="production", **kw).check_auth_settings()

    with pytest.raises(ValueError, match="GOOGLE_CLIENT_ID.*SESSION_SECRET"):
        check()
    check(
        GOOGLE_CLIENT_ID="id",
        GOOGLE_CLIENT_SECRET=SecretStr("secret"),
        SESSION_SECRET=SecretStr("s"),
    )
    # 非正式環境缺設定只是功能不能用，不擋啟動
    make_settings(ENVIRONMENT="local").check_auth_settings()


# ---- 登入狀態 ----


async def test_me_requires_login(auth_client: AsyncClient) -> None:
    assert (await auth_client.get("/auth/me")).status_code == 401


async def test_config_reports_what_is_available(
    auth_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert (await auth_client.get("/auth/config")).json() == {
        "google": True,
        "dev_login": False,
    }
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", None)
    monkeypatch.setattr(settings, "DEV_LOGIN_ENABLED", True)
    assert (await auth_client.get("/auth/config")).json() == {
        "google": False,
        "dev_login": True,
    }


async def test_dev_login_then_me_then_logout(
    auth_client: AsyncClient, session: AsyncSession
) -> None:
    login = await auth_client.post("/auth/dev-login", json={"email": "Dev@Example.com"})
    assert login.status_code == 200
    assert login.json()["email"] == "dev@example.com"

    me = await auth_client.get("/auth/me")
    assert me.status_code == 200
    assert me.json() == login.json()

    assert (await auth_client.post("/auth/logout")).status_code == 204
    assert (await auth_client.get("/auth/me")).status_code == 401
    assert await user_count(session) == 1  # 登出不刪使用者


async def test_dev_login_reuses_the_same_user(
    auth_client: AsyncClient, session: AsyncSession
) -> None:
    first = (
        await auth_client.post("/auth/dev-login", json={"email": "a@x.com"})
    ).json()
    again = (
        await auth_client.post("/auth/dev-login", json={"email": "A@x.com"})
    ).json()
    other = (
        await auth_client.post("/auth/dev-login", json={"email": "b@x.com"})
    ).json()
    assert first["id"] == again["id"] != other["id"]
    assert await user_count(session) == 2


@pytest.mark.parametrize("email", ["", "no-at-sign", "a@", "@b.com", "a b@c.com"])
async def test_dev_login_rejects_bad_email(
    auth_client: AsyncClient, email: str
) -> None:
    assert (
        await auth_client.post("/auth/dev-login", json={"email": email})
    ).status_code == 422


async def test_session_of_a_deleted_user_is_rejected(
    auth_client: AsyncClient, session: AsyncSession
) -> None:
    await auth_client.post("/auth/dev-login", json={"email": "gone@x.com"})
    user = (await session.exec(sm_select(User))).one()
    await session.delete(user)
    await session.commit()
    assert (await auth_client.get("/auth/me")).status_code == 401


async def test_a_tampered_session_cookie_is_rejected(auth_client: AsyncClient) -> None:
    await auth_client.post("/auth/dev-login", json={"email": "a@x.com"})
    value = auth_client.cookies["session"]
    auth_client.cookies.clear()
    auth_client.cookies.set("session", value[:-4] + "AAAA")  # 簽章對不上
    assert (await auth_client.get("/auth/me")).status_code == 401


# ---- Google ----


async def test_login_redirects_to_google_with_the_public_redirect_uri(
    auth_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://app.example.com/")
    seen = fake_google(monkeypatch)
    response = await auth_client.get("/auth/google/login")
    assert response.status_code == 307
    assert response.headers["location"].startswith("https://accounts.google.test/")
    # 用設定的對外網址，不是後端看到的 Host
    assert seen["redirect_uri"] == (
        f"https://app.example.com{settings.API_V1_STR}/auth/google/callback"
    )


async def test_callback_creates_the_user_and_logs_in(
    auth_client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_google(monkeypatch)
    response = await auth_client.get("/auth/google/callback")
    assert response.status_code == 303
    assert response.headers["location"] == "/account"

    me = (await auth_client.get("/auth/me")).json()
    assert me["email"] == "Alice@Example.com"
    assert me["name"] == "Alice"
    user = (await session.exec(sm_select(User))).one()
    assert user.google_sub == "google-sub-1"


async def test_callback_updates_an_existing_user(
    auth_client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_google(monkeypatch)
    await auth_client.get("/auth/google/callback")
    fake_google(
        monkeypatch, {**USERINFO, "email": "new@example.com", "name": "Alice L"}
    )
    await auth_client.get("/auth/google/callback")

    assert await user_count(session) == 1
    user = (await session.exec(sm_select(User))).one()
    assert (user.email, user.name) == ("new@example.com", "Alice L")


async def test_callback_goes_back_to_the_requested_page(
    auth_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_google(monkeypatch)
    await auth_client.get("/auth/google/login", params={"next": "/policies"})
    response = await auth_client.get("/auth/google/callback")
    assert response.headers["location"] == "/policies"


async def test_callback_ignores_an_offsite_next(
    auth_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_google(monkeypatch)
    await auth_client.get("/auth/google/login", params={"next": "https://evil.com"})
    response = await auth_client.get("/auth/google/callback")
    assert response.headers["location"] == "/account"


async def test_allowlist_blocks_other_accounts(
    auth_client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "ALLOWED_EMAILS", "someone@example.com")
    fake_google(monkeypatch)
    response = await auth_client.get("/auth/google/callback")
    assert response.status_code == 303
    assert response.headers["location"] == "/login?error=not_allowed"
    assert (await auth_client.get("/auth/me")).status_code == 401
    assert await user_count(session) == 0  # 被擋下的人不留任何資料


async def test_allowlist_lets_listed_accounts_in_ignoring_case(
    auth_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "ALLOWED_EMAILS", "alice@example.com")
    fake_google(monkeypatch)
    response = await auth_client.get("/auth/google/callback")
    assert response.headers["location"] == "/account"


async def test_unverified_email_is_rejected(
    auth_client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_google(monkeypatch, {**USERINFO, "email_verified": False})
    response = await auth_client.get("/auth/google/callback")
    assert response.headers["location"] == "/login?error=oauth_failed"
    assert await user_count(session) == 0


@pytest.mark.parametrize("missing", ["sub", "email"])
async def test_incomplete_userinfo_is_rejected(
    auth_client: AsyncClient, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    fake_google(monkeypatch, {k: v for k, v in USERINFO.items() if k != missing})
    response = await auth_client.get("/auth/google/callback")
    assert response.headers["location"] == "/login?error=oauth_failed"


async def test_google_error_goes_back_to_the_login_page(
    auth_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def denied(_request: Any) -> dict[str, Any]:
        raise OAuthError(error="access_denied")

    monkeypatch.setattr(oauth.google, "authorize_access_token", denied)
    response = await auth_client.get("/auth/google/callback")
    assert response.status_code == 303
    assert response.headers["location"] == "/login?error=oauth_failed"


async def test_failed_login_does_not_keep_an_old_session(
    auth_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await auth_client.post("/auth/dev-login", json={"email": "a@x.com"})
    assert (await auth_client.get("/auth/me")).status_code == 200

    monkeypatch.setattr(settings, "ALLOWED_EMAILS", "someone@example.com")
    fake_google(monkeypatch)
    await auth_client.get("/auth/google/callback")
    assert (await auth_client.get("/auth/me")).status_code == 401


async def test_google_endpoints_say_so_when_not_configured(
    auth_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", None)
    assert (await auth_client.get("/auth/google/login")).status_code == 503
    assert (await auth_client.get("/auth/google/callback")).status_code == 503
