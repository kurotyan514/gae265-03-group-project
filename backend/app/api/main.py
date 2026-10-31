from fastapi import APIRouter

from app.api.routes import dev, health, ingest, insurances, quote
from app.core.config import settings


def build_api_router(environment: str) -> APIRouter:
    router = APIRouter()
    router.include_router(health.router)
    router.include_router(insurances.router)
    router.include_router(quote.router)
    if environment != "production":
        router.include_router(dev.router)  # 沒有登入保護，正式環境不註冊
        router.include_router(ingest.router)  # 同上：上傳會寫入正式表
    return router


api_router = build_api_router(settings.ENVIRONMENT)
