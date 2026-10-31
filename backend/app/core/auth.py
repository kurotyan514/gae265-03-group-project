"""使用者登入（ADR-0008）：Google OAuth client、session 設定與使用者的建立。"""

import secrets

from authlib.integrations.starlette_client import OAuth
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import Settings, settings
from app.models import User

GOOGLE_METADATA_URL = "https://accounts.google.com/.well-known/openid-configuration"
SESSION_MAX_AGE = 14 * 24 * 60 * 60  # 秒；cookie 與簽章的有效期

# 沒設 SESSION_SECRET 的非正式環境用：每次啟動都不同，重啟後舊的 session 失效。
# 正式環境缺它會在啟動時被 check_auth_settings 擋下。
_EPHEMERAL_SECRET = secrets.token_hex(32)

oauth = OAuth()
oauth.register(
    name="google",
    client_id=settings.GOOGLE_CLIENT_ID,
    client_secret=(
        settings.GOOGLE_CLIENT_SECRET.get_secret_value()
        if settings.GOOGLE_CLIENT_SECRET
        else None
    ),
    server_metadata_url=GOOGLE_METADATA_URL,
    client_kwargs={"scope": "openid email profile"},
)


def session_secret(s: Settings = settings) -> str:
    if s.SESSION_SECRET is not None:
        return s.SESSION_SECRET.get_secret_value()
    return _EPHEMERAL_SECRET


def is_email_allowed(email: str, s: Settings = settings) -> bool:
    """白名單留空代表不限；有填就只放行名單內的 email（不分大小寫）。"""
    allowed = s.allowed_emails
    return not allowed or email.strip().lower() in allowed


def safe_next_path(next_path: str | None) -> str:
    """登入後要回去的頁面：只接受站內路徑，避免被拿來導向別的網站。"""
    if (
        next_path
        and next_path.startswith("/")
        and not next_path.startswith("//")
        and "\\" not in next_path
    ):
        return next_path
    return "/account"


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
