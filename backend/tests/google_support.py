"""Google 登入與授權測試的共用工具（ADR-0020）：測試設定、假的 Google 用戶端。不連 Google。"""

from typing import Any

import pytest
from app.core.config import settings
from app.core.google_oauth import GoogleIdentity, GoogleOAuthError, TokenResponse
from cryptography.fernet import Fernet
from pydantic import SecretStr

# Google 登入與授權的四個設定；金鑰要是合法的 Fernet 金鑰
GOOGLE_SETTINGS: dict[str, Any] = {
    "GOOGLE_CLIENT_ID": "test-client.apps.googleusercontent.com",
    "GOOGLE_CLIENT_SECRET": SecretStr("test-client-secret"),
    "PUBLIC_BASE_URL": "https://travel.example.com",
    "TOKEN_ENCRYPTION_KEY": SecretStr(Fernet.generate_key().decode()),
}

CALLBACK_URI = "https://travel.example.com/api/v1/auth/google/callback"


def use_google_settings(monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> None:
    """讓全域 settings 用測試的 Google 設定，不受本機 .env 影響。"""
    for name, value in {**GOOGLE_SETTINGS, **overrides}.items():
        monkeypatch.setattr(settings, name, value)


def google_tokens(
    *,
    sub: str = "google-sub-1",
    email: str | None = "carol@example.com",
    email_verified: bool = True,
    name: str | None = "Carol",
    scopes: tuple[str, ...] = ("openid", "email", "profile"),
    refresh_token: str | None = None,
    with_identity: bool = True,
) -> TokenResponse:
    """假的「用授權碼換來的 token」。"""
    identity = (
        GoogleIdentity(sub=sub, email=email, email_verified=email_verified, name=name)
        if with_identity
        else None
    )
    return TokenResponse(
        access_token="fake-access-token",
        refresh_token=refresh_token,
        scopes=scopes,
        identity=identity,
    )


class FakeGoogleOAuthClient:
    """假的 Google：回傳事先設定好的結果，並記下被呼叫了什麼。"""

    def __init__(self) -> None:
        self.tokens: TokenResponse | None = None
        self.exchange_error: GoogleOAuthError | None = None
        self.exchanged: list[tuple[str, str]] = []
        # refresh token → 換發結果（新的 access token 或要丟出的例外）
        self.refresh_results: dict[str, str | Exception] = {}
        self.refreshed: list[str] = []
        self.revoke_error: GoogleOAuthError | None = None
        self.folder_error: GoogleOAuthError | None = None
        self.revoked: list[str] = []
        self.folders: list[str] = []

    async def exchange_code(self, code: str, redirect_uri: str) -> TokenResponse:
        self.exchanged.append((code, redirect_uri))
        if self.exchange_error is not None:
            raise self.exchange_error
        assert self.tokens is not None, "測試沒有設定假的 token 回應"
        return self.tokens

    async def refresh_access_token(self, refresh_token: str) -> str:
        self.refreshed.append(refresh_token)
        result = self.refresh_results.get(refresh_token, "fresh-access-token")
        if isinstance(result, Exception):
            raise result
        return result

    async def revoke(self, token: str) -> None:
        self.revoked.append(token)
        if self.revoke_error is not None:
            raise self.revoke_error

    async def create_drive_folder(self, access_token: str, name: str) -> str:
        if self.folder_error is not None:
            raise self.folder_error
        self.folders.append(name)
        return f"folder-{len(self.folders)}"


# ---- 走一次瀏覽器流程 ----


def query(url: str) -> dict[str, str]:
    from urllib.parse import parse_qs, urlsplit

    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


async def start_google(client: Any, path: str, **params: str) -> str:
    """打開導向 Google 的路由（登入或授權），回傳這次的 state。"""
    response = await client.get(path, params=params)
    assert response.status_code == 302, response.text
    return query(response.headers["location"])["state"]


async def google_redirects_back(client: Any, state: str, **params: str) -> str:
    """Google 導回 callback，回傳被導到哪裡。"""
    response = await client.get(
        "/auth/google/callback", params={"code": "the-code", "state": state, **params}
    )
    assert response.status_code == 302, response.text
    return response.headers["location"]


async def log_in_with_google(
    client: Any,
    fake: FakeGoogleOAuthClient,
    *,
    sub: str = "google-sub-1",
    email: str = "carol@example.com",
) -> None:
    """用 Google 登入一位使用者。"""
    state = await start_google(client, "/auth/google/login")
    fake.tokens = google_tokens(sub=sub, email=email)
    assert await google_redirects_back(client, state) == "/"


async def authorize_with_google(
    client: Any,
    fake: FakeGoogleOAuthClient,
    *,
    purpose: str = "drive",
    scopes: tuple[str, ...],
    refresh_token: str = "rt-1",
    sub: str = "google-sub-1",
) -> str:
    """已登入的使用者完成一次 Drive 或 Gmail 授權，回傳被導回哪裡。"""
    state = await start_google(
        client, "/auth/google/authorize", purpose=purpose, next="/dev/incident"
    )
    fake.tokens = google_tokens(sub=sub, scopes=scopes, refresh_token=refresh_token)
    return await google_redirects_back(client, state)
