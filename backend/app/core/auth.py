"""使用者登入（ADR-0008）：session 設定與使用者的建立。"""

import secrets
from datetime import UTC, datetime

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import Settings, settings
from app.models import Identity, User

SESSION_MAX_AGE = 14 * 24 * 60 * 60  # 秒；cookie 與簽章的有效期

# 沒設 SESSION_SECRET 的非正式環境用：每次啟動都不同，重啟後舊的 session 失效。
# 正式環境缺它會在啟動時被 check_auth_settings 擋下。
_EPHEMERAL_SECRET = secrets.token_hex(32)


def session_secret(s: Settings = settings) -> str:
    if s.SESSION_SECRET is not None:
        return s.SESSION_SECRET.get_secret_value()
    return _EPHEMERAL_SECRET


async def upsert_user(
    session: AsyncSession,
    provider: str,
    provider_user_id: str,
    email: str,
    name: str | None,
    email_verified: bool = False,
) -> User:
    """以（提供者，提供者的帳號識別）找使用者；email 或名稱變了就更新，沒有就建立。"""
    identity = (
        await session.exec(
            select(Identity).where(
                Identity.provider == provider,
                Identity.provider_user_id == provider_user_id,
            )
        )
    ).first()
    user = await session.get(User, identity.user_id) if identity else None
    if user is None:
        user = User(email=email, name=name)
        session.add(user)
        await session.flush()
        identity = Identity(
            user_id=user.id, provider=provider, provider_user_id=provider_user_id
        )
    else:
        user.email = email
        user.name = name
        session.add(user)
    assert identity is not None
    identity.provider_email = email
    identity.email_verified = email_verified
    identity.last_used_at = datetime.now(UTC)
    session.add(identity)
    await session.commit()
    await session.refresh(user)
    return user
