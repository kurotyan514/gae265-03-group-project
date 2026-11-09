import uuid
from typing import Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep, is_admin
from app.core.auth import upsert_user
from app.core.config import settings
from app.models import Identity, User

router = APIRouter(prefix="/auth", tags=["auth"])
# 測試登入；build_api_router 只在非 production 且 DEV_LOGIN_ENABLED 時註冊
dev_router = APIRouter(prefix="/auth", tags=["auth"])


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    name: str | None
    login_provider: Literal["google", "dev"] | None = Field(
        default=None,
        description="用什麼登入；只有 google 能授權 Drive 與 Gmail（ADR-0020）",
    )
    is_admin: bool = Field(
        default=False, description="是不是管理者（email 在 ADMIN_EMAILS 名單內）"
    )


async def user_out(session: SessionDep, user: User) -> UserOut:
    identity = (
        await session.exec(select(Identity).where(Identity.user_id == user.id))
    ).first()
    provider = identity.provider if identity else None
    return UserOut(
        id=user.id,
        email=user.email,
        name=user.name,
        login_provider=provider if provider in ("google", "dev") else None,
        is_admin=is_admin(user),
    )


class AuthConfig(BaseModel):
    dev_login: bool = Field(description="是否開放測試登入（只有非 production）")
    google_login: bool = Field(description="是否開放 Google 登入（Google 設定齊全）")


class DevLoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+$")
    name: str | None = Field(default=None, max_length=100)


@router.get("/config")
async def auth_config() -> AuthConfig:
    return AuthConfig(
        dev_login=settings.dev_login_enabled,
        google_login=settings.google_login_enabled,
    )


@router.get("/me")
async def auth_me(user: CurrentUser, session: SessionDep) -> UserOut:
    return await user_out(session, user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def auth_logout(request: Request) -> Response:
    request.session.clear()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@dev_router.post("/dev-login")
async def dev_login(body: DevLoginIn, request: Request, session: SessionDep) -> UserOut:
    email = body.email.lower()
    user = await upsert_user(session, "dev", email, email, body.name)
    request.session.clear()
    request.session["user_id"] = str(user.id)
    return await user_out(session, user)
