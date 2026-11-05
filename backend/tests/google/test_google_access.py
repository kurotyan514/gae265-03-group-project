"""GoogleAccess 的正式實作（ADR-0020）：6、7 號用它拿使用者的 Google token。

直接在測試資料庫建使用者與 google_grant，Google 用假的，不連網路。
"""

import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest
from app.agents.registry import UnavailableGoogleAccess, get_google_access
from app.contracts import UserContext
from app.core.google_grants import GrantGoogleAccess
from app.core.google_oauth import (
    DRIVE_SCOPE,
    GMAIL_SCOPE,
    GoogleOAuthError,
    InvalidGrantError,
)
from app.core.token_cipher import cipher_from_settings
from app.models import GoogleGrant, User
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel.ext.asyncio.session import AsyncSession

from tests.google_support import FakeGoogleOAuthClient, use_google_settings

REFRESH_TOKEN = "rt-secret-value"


@pytest.fixture
async def fake_google(monkeypatch: pytest.MonkeyPatch) -> FakeGoogleOAuthClient:
    use_google_settings(monkeypatch)
    return FakeGoogleOAuthClient()


@pytest.fixture
def access(
    engine: AsyncEngine, fake_google: FakeGoogleOAuthClient
) -> GrantGoogleAccess:
    return GrantGoogleAccess(
        session_factory=lambda: AsyncSession(engine, expire_on_commit=False),
        google=fake_google,
    )


@pytest.fixture
async def user(session: AsyncSession) -> AsyncGenerator[UserContext]:
    row = User(email="carol@example.com", name="Carol")
    session.add(row)
    await session.commit()
    yield UserContext(user_id=row.id, email=row.email)


async def add_grant(
    session: AsyncSession,
    user: UserContext,
    *,
    scopes: tuple[str, ...] = ("openid", DRIVE_SCOPE),
    status: str = "active",
    with_token: bool = True,
) -> None:
    session.add(
        GoogleGrant(
            user_id=user.user_id,
            scopes=list(scopes),
            refresh_token_encrypted=(
                cipher_from_settings().encrypt(REFRESH_TOKEN) if with_token else None
            ),
            status=status,
            granted_at=datetime.now(UTC),
        )
    )
    await session.commit()


async def grant_status(session: AsyncSession) -> str:
    from sqlmodel import select

    session.expire_all()
    return (await session.exec(select(GoogleGrant))).one().status


# ---- 拿得到 token ----


@pytest.mark.parametrize("scope", ["drive.file", DRIVE_SCOPE])
async def test_active_grant_gives_a_fresh_access_token(
    access: GrantGoogleAccess,
    fake_google: FakeGoogleOAuthClient,
    session: AsyncSession,
    user: UserContext,
    scope: str,
) -> None:
    await add_grant(session, user)
    assert await access.access_token(user, scope) == "fresh-access-token"
    assert fake_google.refreshed == [REFRESH_TOKEN]


@pytest.mark.parametrize("scope", ["gmail.compose", "gmail.send", GMAIL_SCOPE])
async def test_gmail_compose_grant_also_serves_gmail_send(
    access: GrantGoogleAccess, session: AsyncSession, user: UserContext, scope: str
) -> None:
    await add_grant(session, user, scopes=("openid", GMAIL_SCOPE))
    assert await access.access_token(user, scope) == "fresh-access-token"


async def test_drive_and_gmail_tokens_come_from_the_same_grant(
    access: GrantGoogleAccess, session: AsyncSession, user: UserContext
) -> None:
    # 7 號寄信：Drive 讀附件、Gmail 寄信
    await add_grant(session, user, scopes=("openid", DRIVE_SCOPE, GMAIL_SCOPE))
    assert await access.access_token(user, "drive.file") is not None
    assert await access.access_token(user, "gmail.send") is not None


# ---- 拿不到 token：回 None，不丟例外 ----


async def test_no_grant_gives_none(
    access: GrantGoogleAccess, fake_google: FakeGoogleOAuthClient, user: UserContext
) -> None:
    assert await access.access_token(user, "drive.file") is None
    assert fake_google.refreshed == []


async def test_missing_permission_gives_none_without_asking_google(
    access: GrantGoogleAccess,
    fake_google: FakeGoogleOAuthClient,
    session: AsyncSession,
    user: UserContext,
) -> None:
    await add_grant(session, user, scopes=("openid", GMAIL_SCOPE))  # 只授權 Gmail
    assert await access.access_token(user, "drive.file") is None
    assert fake_google.refreshed == []


@pytest.mark.parametrize("status", ["revoked", "invalid"])
async def test_revoked_or_invalid_grant_gives_none(
    access: GrantGoogleAccess,
    fake_google: FakeGoogleOAuthClient,
    session: AsyncSession,
    user: UserContext,
    status: str,
) -> None:
    await add_grant(session, user, status=status, with_token=status == "invalid")
    assert await access.access_token(user, "drive.file") is None
    assert fake_google.refreshed == []


async def test_expired_grant_gives_none_and_is_marked_invalid(
    access: GrantGoogleAccess,
    fake_google: FakeGoogleOAuthClient,
    session: AsyncSession,
    user: UserContext,
) -> None:
    await add_grant(session, user)
    fake_google.refresh_results[REFRESH_TOKEN] = InvalidGrantError("已失效")

    assert await access.access_token(user, "drive.file") is None
    assert await grant_status(session) == "invalid"


async def test_google_being_down_gives_none_but_keeps_the_grant(
    access: GrantGoogleAccess,
    fake_google: FakeGoogleOAuthClient,
    session: AsyncSession,
    user: UserContext,
) -> None:
    await add_grant(session, user)
    fake_google.refresh_results[REFRESH_TOKEN] = GoogleOAuthError("Google 回應 503")

    assert await access.access_token(user, "drive.file") is None
    assert await grant_status(session) == "active"


@pytest.mark.parametrize("scope", ["calendar", "https://www.googleapis.com/auth/drive"])
async def test_unknown_scope_gives_none(
    access: GrantGoogleAccess, session: AsyncSession, user: UserContext, scope: str
) -> None:
    await add_grant(session, user, scopes=("openid", DRIVE_SCOPE, GMAIL_SCOPE))
    assert await access.access_token(user, scope) is None


async def test_tokens_and_email_are_not_logged(
    access: GrantGoogleAccess,
    session: AsyncSession,
    user: UserContext,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await add_grant(session, user)
    with caplog.at_level(logging.DEBUG):
        token = await access.access_token(user, "drive.file")
    assert token is not None
    for secret in (REFRESH_TOKEN, token, user.email):
        assert secret not in caplog.text


# ---- 平台拿到哪一種 ----


def test_platform_uses_the_real_grants_when_google_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_google_settings(monkeypatch)
    assert isinstance(get_google_access(), GrantGoogleAccess)


async def test_platform_has_no_tokens_when_google_is_not_configured(
    monkeypatch: pytest.MonkeyPatch, user: UserContext
) -> None:
    use_google_settings(monkeypatch, GOOGLE_CLIENT_ID=None)
    google = get_google_access()
    assert isinstance(google, UnavailableGoogleAccess)
    assert await google.access_token(user, "drive.file") is None
