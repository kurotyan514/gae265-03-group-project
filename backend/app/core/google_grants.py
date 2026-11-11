"""使用者的 Google 授權（google_grant）的共用邏輯（ADR-0020）。

查授權狀態的路由與 6、7 號用的 GoogleAccess（GrantGoogleAccess）都用這裡，判斷才會一致：
- 換發 access token；Google 回 invalid_grant（過期或被撤銷）或解不開 token 時，標成 invalid。
- 取消授權：請 Google 撤銷、清空 token、標成 revoked，紀錄保留當同意紀錄。
token 只在記憶體裡用，不寫 log。
"""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.contracts import UserContext
from app.core.google_oauth import (
    DRIVE_FOLDER_NAME,
    DRIVE_SCOPE,
    GMAIL_SCOPE,
    GoogleOAuthClient,
    GoogleOAuthError,
    HttpGoogleOAuthClient,
    InvalidGrantError,
)
from app.core.token_cipher import TokenDecryptError, cipher_from_settings
from app.models import GoogleGrant


async def grant_of(session: AsyncSession, user_id: uuid.UUID) -> GoogleGrant | None:
    return (
        await session.exec(select(GoogleGrant).where(GoogleGrant.user_id == user_id))
    ).first()


def is_usable(grant: GoogleGrant | None) -> bool:
    return (
        grant is not None
        and grant.status == "active"
        and grant.refresh_token_encrypted is not None
    )


async def fresh_access_token(
    session: AsyncSession, grant: GoogleGrant, google: GoogleOAuthClient
) -> str | None:
    """用 refresh token 換一把新的 access token。

    授權已失效（invalid_grant、解不開）時標成 invalid 並回 None。
    Google 暫時連不上時丟 GoogleOAuthError，不改狀態，由呼叫端決定怎麼處理。
    """
    if not is_usable(grant):
        return None
    assert grant.refresh_token_encrypted is not None
    try:
        refresh_token = cipher_from_settings().decrypt(grant.refresh_token_encrypted)
        access_token = await google.refresh_access_token(refresh_token)
    except InvalidGrantError, TokenDecryptError:
        grant.status = "invalid"
        session.add(grant)
        await session.commit()
        return None
    grant.last_refreshed_at = datetime.now(UTC)
    session.add(grant)
    await session.commit()
    return access_token


async def revoke_grant(
    session: AsyncSession, grant: GoogleGrant, google: GoogleOAuthClient
) -> None:
    """取消授權：請 Google 撤銷，再清空 token。

    Google 暫時失敗時照樣清空：使用者的意思是不要再讓系統存取，清掉之後系統就用不到了；
    使用者也可以到 Google 帳號的「第三方存取權」自己移除。
    """
    if grant.refresh_token_encrypted is not None:
        try:
            token = cipher_from_settings().decrypt(grant.refresh_token_encrypted)
            await google.revoke(token)
        except GoogleOAuthError, TokenDecryptError:
            pass
    grant.refresh_token_encrypted = None
    grant.status = "revoked"
    grant.revoked_at = datetime.now(UTC)
    session.add(grant)
    await session.commit()


# 6、7 號傳進來的 scope 可以是短名或完整網址。gmail.compose 本身就能寄信，
# 所以要 gmail.send（7 號交接說明的寫法）時也用 gmail.compose 的授權。
_SCOPES = {
    "drive.file": DRIVE_SCOPE,
    "gmail.compose": GMAIL_SCOPE,
    "gmail.send": GMAIL_SCOPE,
}
_SCOPE_PREFIX = "https://www.googleapis.com/auth/"


def granted_scope_for(scope: str) -> str | None:
    """agent 要的 scope 對應到我們請求的哪一個；不認得的回 None。"""
    return _SCOPES.get(scope.removeprefix(_SCOPE_PREFIX))


def _session_from_app_engine() -> AsyncSession:
    from app.core.db import engine

    return AsyncSession(engine, expire_on_commit=False)


def _google_from_settings() -> GoogleOAuthClient:
    from app.core.config import settings

    assert settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET
    return HttpGoogleOAuthClient(
        settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET.get_secret_value()
    )


class GrantGoogleAccess:
    """`GoogleAccess` 的正式實作：讀使用者的 google_grant，換一把新的 access token 給 agent。

    沒有授權、已取消、已失效、沒有要的 scope、或 Google 暫時連不上，一律回 None，不丟例外；
    6 號回 needs_review、7 號回 failed（請使用者先授權）。
    平台呼叫 get_google_access() 時沒有傳資料庫連線，所以這裡自己開一個。
    """

    def __init__(
        self,
        *,
        session_factory: Callable[[], AsyncSession] | None = None,
        google: GoogleOAuthClient | None = None,
    ) -> None:
        self._session_factory = session_factory or _session_from_app_engine
        self._google = google

    async def access_token(self, user: UserContext, scope: str) -> str | None:
        wanted = granted_scope_for(scope)
        if wanted is None:
            return None
        async with self._session_factory() as session:
            grant = await grant_of(session, user.user_id)
            if grant is None or not is_usable(grant) or wanted not in grant.scopes:
                return None
            google = self._google or _google_from_settings()
            try:
                return await fresh_access_token(session, grant, google)
            except GoogleOAuthError:
                return None  # Google 暫時連不上：這次拿不到，但不把授權標成失效

    async def drive_folder_id(self, user: UserContext) -> str | None:
        """使用者 Drive 裡的理賠資料夾編號；沒有有效的 Drive 授權時回 None。

        授權當時建資料夾失敗的話，編號是空的（授權照樣存下來）。這裡用換發的 token 現場補建並存起來，
        不要讓 6 號卡在「有授權卻沒有資料夾」。Google 暫時連不上時回 None，下次再試。
        """
        async with self._session_factory() as session:
            grant = await grant_of(session, user.user_id)
            if grant is None or not is_usable(grant) or DRIVE_SCOPE not in grant.scopes:
                return None
            if grant.drive_folder_id:
                return grant.drive_folder_id
            google = self._google or _google_from_settings()
            try:
                token = await fresh_access_token(session, grant, google)
                if token is None:
                    return None
                grant.drive_folder_id = await google.create_drive_folder(
                    token, DRIVE_FOLDER_NAME
                )
            except GoogleOAuthError:
                return None
            session.add(grant)
            await session.commit()
            return grant.drive_folder_id
