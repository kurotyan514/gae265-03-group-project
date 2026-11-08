"""後台寫入端點只有管理者能用（#47、ADR-0016）：沒登入 401、不是管理者 403、名單留空沒有人能用。

涵蓋兩組端點：條款上傳（/ingest）、合訂本拆分（/ingest/bundles）。
管理者名單是 `ADMIN_EMAILS`（逗號分隔、不分大小寫、去空白），只看登入後的 email。
"""

import uuid
from collections.abc import AsyncGenerator

import pytest
from app.api.deps import current_user
from app.core.config import settings
from app.main import app
from app.models import User
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

JOB = uuid.uuid4()
ENDPOINTS = [
    ("GET", "/ingest/jobs", {}),
    ("GET", f"/ingest/jobs/{JOB}", {}),
    ("GET", f"/ingest/jobs/{JOB}/events", {}),  # SSE：權限要在建立串流之前就檢查
    ("POST", f"/ingest/jobs/{JOB}/approve", {}),
    ("GET", "/ingest/bundles", {}),
]


@pytest.fixture
async def member(session: AsyncSession) -> AsyncGenerator[User]:
    """已登入、但 email 不在管理者名單內的一般使用者。"""
    user = User(email="member@example.com")
    session.add(user)
    await session.commit()
    app.dependency_overrides[current_user] = lambda: user
    yield user
    app.dependency_overrides.pop(current_user, None)


@pytest.mark.parametrize(("method", "path", "kwargs"), ENDPOINTS)
async def test_沒登入回_401(client: AsyncClient, method, path, kwargs) -> None:
    response = await client.request(method, path, **kwargs)

    assert response.status_code == 401, (method, path, response.text)


@pytest.mark.usefixtures("member")
@pytest.mark.parametrize(("method", "path", "kwargs"), ENDPOINTS)
async def test_登入但不是管理者回_403(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, method, path, kwargs
) -> None:
    monkeypatch.setattr(settings, "ADMIN_EMAILS", "someone-else@example.com")

    response = await client.request(method, path, **kwargs)

    assert response.status_code == 403, (method, path, response.text)
    assert response.json()["detail"] == "需要管理者權限"


@pytest.mark.usefixtures("logged_in")
@pytest.mark.parametrize(("method", "path", "kwargs"), ENDPOINTS)
async def test_管理者不會被權限擋下(client: AsyncClient, method, path, kwargs) -> None:
    response = await client.request(method, path, **kwargs)

    assert response.status_code not in (401, 403), (method, path, response.text)


@pytest.mark.usefixtures("logged_in")
@pytest.mark.parametrize("empty", ["", "  ", " , ,"])
async def test_名單留空沒有人能用(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, empty: str
) -> None:
    monkeypatch.setattr(settings, "ADMIN_EMAILS", empty)

    response = await client.get("/ingest/jobs")

    assert response.status_code == 403


@pytest.mark.usefixtures("logged_in")
async def test_名單不分大小寫_也會去掉空白(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        settings, "ADMIN_EMAILS", " Other@Example.com ,  ADMIN@EXAMPLE.COM , "
    )

    response = await client.get("/ingest/jobs")

    assert response.status_code == 200


@pytest.mark.usefixtures("member")
async def test_auth_me_帶出是不是管理者(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "ADMIN_EMAILS", "boss@example.com")
    assert (await client.get("/auth/me")).json()["is_admin"] is False

    monkeypatch.setattr(settings, "ADMIN_EMAILS", "Member@example.com")
    assert (await client.get("/auth/me")).json()["is_admin"] is True
