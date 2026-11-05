from fastapi import APIRouter

from app.api.routes import (
    auth,
    comparisons,
    conversations,
    dev,
    google_auth,
    health,
    incidents,
    ingest,
    insurances,
    plan_premiums,
    plans,
    policies,
    quote,
)
from app.core.config import settings


def build_api_router(environment: str, dev_login: bool = False) -> APIRouter:
    router = APIRouter()
    router.include_router(health.router)
    router.include_router(auth.router)
    router.include_router(google_auth.router)
    router.include_router(insurances.router)
    router.include_router(plans.router)
    router.include_router(plan_premiums.router)
    router.include_router(policies.router)
    router.include_router(comparisons.router)
    router.include_router(conversations.router)
    router.include_router(incidents.router)
    router.include_router(quote.router)
    # 條款上傳整組都要登入，所以所有環境都註冊（ADR-0023）
    router.include_router(ingest.router)
    if environment != "production":
        router.include_router(dev.router)  # 沒有登入保護，正式環境不註冊
        # 任何 email 都能登入，所以要明確打開才有（settings.dev_login_enabled）
        if dev_login:
            router.include_router(auth.dev_router)
    return router


api_router = build_api_router(settings.ENVIRONMENT, settings.dev_login_enabled)
