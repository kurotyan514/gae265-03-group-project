from fastapi import APIRouter

from app.api.routes import (
    admin_excluded,
    admin_rules,
    auth,
    bundles,
    comparisons,
    conversations,
    dev,
    dev_document,
    dev_package,
    google_auth,
    health,
    incidents,
    ingest,
    insurances,
    plan_premiums,
    plans,
    policies,
    questions,
    quote,
    scenarios,
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
    router.include_router(scenarios.router)
    router.include_router(questions.router)
    router.include_router(conversations.router)
    router.include_router(incidents.router)
    router.include_router(quote.router)
    # 條款上傳整組都要登入，所以所有環境都註冊（ADR-0023）
    router.include_router(ingest.router)
    router.include_router(bundles.router)
    router.include_router(admin_rules.router)  # 條文維護，同樣整組要登入
    router.include_router(admin_rules.insurances_router)
    router.include_router(admin_excluded.router)
    if environment != "production":
        router.include_router(dev.router)  # 沒有登入保護，正式環境不註冊
        router.include_router(dev_document.router)  # 同上：6 號文件辨識的逐步展示
        router.include_router(dev_package.router)  # 同上：7 號打包寄送的範例
        # 任何 email 都能登入，所以要明確打開才有（settings.dev_login_enabled）
        if dev_login:
            router.include_router(auth.dev_router)
    return router


api_router = build_api_router(settings.ENVIRONMENT, settings.dev_login_enabled)
