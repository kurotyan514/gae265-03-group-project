"""Google 登入與授權測試的共用 fixture：假的 Google 與測試用的 API client。"""

from collections.abc import AsyncGenerator

import pytest
from app.api.deps import get_google_oauth_client
from app.core.config import settings
from app.core.db import get_session
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel.ext.asyncio.session import AsyncSession

from tests.google_support import FakeGoogleOAuthClient, use_google_settings
from tests.test_auth_api import make_app


@pytest.fixture
def fake_google() -> FakeGoogleOAuthClient:
    return FakeGoogleOAuthClient()


@pytest.fixture
async def client(
    engine: AsyncEngine,
    fake_google: FakeGoogleOAuthClient,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[AsyncClient]:
    """開了測試登入、Google 用戶端換成假的；全域設定用測試的 Google 設定。"""
    use_google_settings(monkeypatch)
    app = make_app()

    async def override_get_session() -> AsyncGenerator[AsyncSession]:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_google_oauth_client] = lambda: fake_google
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=f"http://test{settings.API_V1_STR}"
    ) as c:
        yield c
