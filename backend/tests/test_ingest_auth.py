"""條款上傳的所有端點都要登入（ADR-0023）：沒登入回 401，登入後才能用。"""

import uuid

import pytest
from app.api.main import build_api_router
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.middleware.sessions import SessionMiddleware

JOB = uuid.uuid4()
PDF = {"file": ("a.pdf", b"%PDF-1.4", "application/pdf")}
FORM = {"insurance_code": "FUBON07", "insurance_name": "旅遊不便險"}

# (方法, 路徑, 其他參數)；涵蓋 ingest 的每一個端點
ENDPOINTS = [
    ("POST", "/ingest/jobs", {"files": PDF, "data": FORM}),
    ("GET", "/ingest/jobs", {}),
    ("GET", f"/ingest/jobs/{JOB}", {}),
    ("POST", f"/ingest/jobs/{JOB}/approve", {}),
    ("POST", f"/ingest/jobs/{JOB}/articles/1/release", {}),
    (
        "POST",
        f"/ingest/jobs/{JOB}/articles/1/edit",
        {"json": {"content": "x", "reason": "y"}},
    ),
    ("POST", f"/ingest/jobs/{JOB}/articles/1/delete", {}),
    ("GET", f"/ingest/jobs/{JOB}/events", {}),
]


@pytest.mark.parametrize(("method", "path", "kwargs"), ENDPOINTS)
async def test_沒登入每個上傳端點都回_401(
    client: AsyncClient, method, path, kwargs
) -> None:
    response = await client.request(method, path, **kwargs)

    assert response.status_code == 401, (method, path, response.text)


@pytest.mark.usefixtures("logged_in")
async def test_登入後可以列出上傳紀錄(client: AsyncClient) -> None:
    response = await client.get("/ingest/jobs")

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize("environment", ["development", "production"])
async def test_所有環境都註冊上傳端點_且都要登入(environment: str) -> None:
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test")
    app.include_router(build_api_router(environment))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/ingest/jobs")

    assert response.status_code == 401  # 不是 404：路由存在，只是要登入


async def test_合訂本拆分清單的端點也都要登入(client: AsyncClient) -> None:
    for method, path in [
        ("POST", "/ingest/bundles"),
        ("GET", "/ingest/bundles"),
        ("GET", f"/ingest/bundles/{JOB}"),
        ("PUT", f"/ingest/bundles/{JOB}"),
        ("POST", f"/ingest/bundles/{JOB}/check"),
        ("POST", f"/ingest/bundles/{JOB}/confirm"),
    ]:
        response = await client.request(method, path)
        assert response.status_code == 401, (method, path)
