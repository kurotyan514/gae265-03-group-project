import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.core.google_oauth import GoogleOAuthClient, HttpGoogleOAuthClient
from app.models import User

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def current_user(request: Request, session: SessionDep) -> User:
    """目前登入的使用者；沒登入、session 壞掉、或使用者已被刪除都回 401。
    測試用 `app.dependency_overrides[current_user]` 換身分。"""
    user = None
    try:
        user_id = uuid.UUID(str(request.session.get("user_id")))
    except ValueError:
        pass
    else:
        user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未登入")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def is_admin(user: User) -> bool:
    """email 在 `ADMIN_EMAILS` 名單內（不分大小寫）；名單留空時沒有人是管理者。"""
    return user.email.strip().lower() in settings.admin_emails


async def require_admin(user: CurrentUser) -> User:
    """後台寫入端點用：沒登入回 401（由 current_user 擋），登入但不是管理者回 403。

    管理者只看登入後的 email，所以其他成員日後換登入實作也不受影響（ADR-0016）。
    """
    if not is_admin(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "需要管理者權限")
    return user


AdminUser = Annotated[User, Depends(require_admin)]


def get_google_oauth_client() -> GoogleOAuthClient:
    """和 Google 對話的用戶端（ADR-0020）；設定不完整時回 503。
    測試用 `app.dependency_overrides[get_google_oauth_client]` 換成假的，不連 Google。"""
    if not settings.google_login_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Google 登入尚未設定")
    assert settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET
    return HttpGoogleOAuthClient(
        settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET.get_secret_value()
    )


GoogleOAuthDep = Annotated[GoogleOAuthClient, Depends(get_google_oauth_client)]
