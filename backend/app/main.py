from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.middleware.sessions import SessionMiddleware

from app.api.main import api_router
from app.core.auth import SESSION_MAX_AGE, session_secret
from app.core.config import settings
from app.core.db import engine
from app.ingest.agent import fail_stale_jobs


def _operation_id_from_route_name(route: APIRoute) -> str:
    """operationId 用路由函式名：前端由 OpenAPI 產生 client，產生出來的函式以它命名，所以路由函式不可同名。"""
    return route.name


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    # 啟動即檢查 LLM 設定，缺必填項時伺服器起不來並印出缺哪些變數
    settings.check_llm_provider()
    settings.check_auth_settings()
    if settings.ENVIRONMENT != "production":
        await fail_stale_jobs(engine)
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    lifespan=lifespan,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    generate_unique_id_function=_operation_id_from_route_name,
)
# 簽章的 httpOnly cookie 當 session（ADR-0008）；SameSite=Lax 讓跨站的 POST 帶不到 cookie
app.add_middleware(
    SessionMiddleware,
    secret_key=session_secret(),
    max_age=SESSION_MAX_AGE,
    same_site="lax",
    https_only=settings.ENVIRONMENT == "production",
)
app.include_router(api_router, prefix=settings.API_V1_STR)
