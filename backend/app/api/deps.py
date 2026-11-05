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
