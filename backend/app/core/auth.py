"""使用者登入（ADR-0008）：session 設定與使用者的建立。"""

import secrets

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import Settings, settings
from app.models import User

SESSION_MAX_AGE = 14 * 24 * 60 * 60  # 秒；cookie 與簽章的有效期

# 沒設 SESSION_SECRET 的非正式環境用：每次啟動都不同，重啟後舊的 session 失效。
# 正式環境缺它會在啟動時被 check_auth_settings 擋下。
_EPHEMERAL_SECRET = secrets.token_hex(32)


def session_secret(s: Settings = settings) -> str:
    if s.SESSION_SECRET is not None:
        return s.SESSION_SECRET.get_secret_value()
    return _EPHEMERAL_SECRET


async def upsert_user(
    session: AsyncSession, google_sub: str, email: str, name: str | None
) -> User:
    """以 google_sub 找使用者；email 或名稱變了就更新，沒有就建立。"""
    user = (
        await session.exec(select(User).where(User.google_sub == google_sub))
    ).first()
    if user is None:
        user = User(google_sub=google_sub, email=email, name=name)
    else:
        user.email = email
        user.name = name
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user
