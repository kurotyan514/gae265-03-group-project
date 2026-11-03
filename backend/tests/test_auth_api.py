"""使用者登入（ADR-0008）：dev-login、session 與 current_user。"""

from collections.abc import AsyncGenerator
from typing import Any

import pytest
from app.api.main import build_api_router
from app.core.config import Settings, settings
from app.core.db import get_session
from app.models import User
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel import func
from sqlmodel import select as sm_select
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.middleware.sessions import SessionMiddleware


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
async def auth_client(engine: AsyncEngine) -> AsyncGenerator[AsyncClient]:
    app = make_app()

    async def override_get_session() -> AsyncGenerator[AsyncSession]:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=f"http://test{settings.API_V1_STR}"
    ) as client:
        yield client


async def user_count(session: AsyncSession) -> int:
    return (await session.exec(sm_select(func.count()).select_from(User))).one()


# ---- 純邏輯 ----


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

    with pytest.raises(ValueError, match="SESSION_SECRET"):
        check()
    check(SESSION_SECRET=SecretStr("s"))
    # 非正式環境缺設定只是功能不能用，不擋啟動
    make_settings(ENVIRONMENT="local").check_auth_settings()


# ---- 登入狀態 ----


async def test_me_requires_login(auth_client: AsyncClient) -> None:
    assert (await auth_client.get("/auth/me")).status_code == 401


async def test_config_reports_what_is_available(
    auth_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert (await auth_client.get("/auth/config")).json() == {"dev_login": False}
    monkeypatch.setattr(settings, "DEV_LOGIN_ENABLED", True)
    assert (await auth_client.get("/auth/config")).json() == {"dev_login": True}


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
