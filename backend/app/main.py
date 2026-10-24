from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.routing import APIRoute

from app.api.main import api_router
from app.core.config import settings


def _operation_id_from_route_name(route: APIRoute) -> str:
    """operationId 用路由函式名：前端由 OpenAPI 產生 client，產生出來的函式以它命名，所以路由函式不可同名。"""
    return route.name


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    # 啟動即檢查 LLM 設定，缺必填項時伺服器起不來並印出缺哪些變數
    settings.check_llm_provider()
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    lifespan=lifespan,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    generate_unique_id_function=_operation_id_from_route_name,
)
app.include_router(api_router, prefix=settings.API_V1_STR)
