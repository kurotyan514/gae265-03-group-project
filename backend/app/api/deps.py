import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_session
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
