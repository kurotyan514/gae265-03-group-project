import uuid
from typing import Annotated

from authlib.integrations.starlette_client import OAuthError
from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, SessionDep
from app.core.auth import is_email_allowed, oauth, safe_next_path, upsert_user
from app.core.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])
# 不用 Google 的測試登入；build_api_router 只在非 production 且 DEV_LOGIN_ENABLED 時註冊
dev_router = APIRouter(prefix="/auth", tags=["auth"])


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    name: str | None


class AuthConfig(BaseModel):
    google: bool = Field(description="後端是否設定了 Google 登入")
    dev_login: bool = Field(description="是否開放測試登入（只有非 production）")


class DevLoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+$")
    name: str | None = Field(default=None, max_length=100)


def _login_failed(request: Request, reason: str) -> RedirectResponse:
    """登入失敗回前端的登入頁，由頁面顯示原因；不留任何 session，也不把細節帶出去。"""
    request.session.clear()
    return RedirectResponse(f"/login?error={reason}", status.HTTP_303_SEE_OTHER)


def _require_google() -> None:
    if not settings.google_login_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Google 登入尚未設定")


@router.get("/config")
async def auth_config() -> AuthConfig:
    return AuthConfig(
        google=settings.google_login_enabled, dev_login=settings.dev_login_enabled
    )


@router.get("/me")
async def auth_me(user: CurrentUser) -> UserOut:
    return UserOut(id=user.id, email=user.email, name=user.name)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def auth_logout(request: Request) -> Response:
    request.session.clear()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/google/login")
async def google_login(
    request: Request, next_path: Annotated[str | None, Query(alias="next")] = None
) -> Response:
    _require_google()
    request.session["next"] = safe_next_path(next_path)
    redirect_uri = (
        f"{settings.PUBLIC_BASE_URL.rstrip('/')}{settings.API_V1_STR}"
        "/auth/google/callback"
    )
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/google/callback")
async def google_callback(request: Request, session: SessionDep) -> RedirectResponse:
    _require_google()
    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError:
        # 使用者在 Google 按取消，或 state 對不上（cookie 被清掉、重複使用）
        return _login_failed(request, "oauth_failed")

    info = token.get("userinfo") or {}
    sub, email = info.get("sub"), info.get("email")
    if not sub or not email or info.get("email_verified") is not True:
        return _login_failed(request, "oauth_failed")
    if not is_email_allowed(email):
        return _login_failed(request, "not_allowed")

    user = await upsert_user(session, str(sub), email, info.get("name"))
    next_path = request.session.get("next")
    request.session.clear()
    request.session["user_id"] = str(user.id)
    return RedirectResponse(safe_next_path(next_path), status.HTTP_303_SEE_OTHER)


@dev_router.post("/dev-login")
async def dev_login(body: DevLoginIn, request: Request, session: SessionDep) -> UserOut:
    email = body.email.lower()
    user = await upsert_user(session, f"dev:{email}", email, body.name)
    request.session.clear()
    request.session["user_id"] = str(user.id)
    return UserOut(id=user.id, email=user.email, name=user.name)
