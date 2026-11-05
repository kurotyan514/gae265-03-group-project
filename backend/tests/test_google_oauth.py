"""後端和 Google OAuth 的對話（ADR-0020）。

用 httpx.MockTransport 當假的網路：檢查送給 Google 的內容，並模擬 Google 的回應，不連網路。
"""

import base64
import json
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from app.core.google_oauth import (
    DRIVE_FOLDER_MIME_TYPE,
    DRIVE_SCOPE,
    GMAIL_SCOPE,
    GoogleOAuthError,
    HttpGoogleOAuthClient,
    InvalidGrantError,
    authorization_url,
    decode_id_token,
    login_url,
)

CLIENT_SECRET = "test-client-secret"
REDIRECT_URI = "https://travel.example.com/api/v1/auth/google/callback"


def query(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


def make_id_token(**claims: Any) -> str:
    def part(data: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    return f"{part({'alg': 'RS256'})}.{part(claims)}.signature"


def make_client(
    handler: Callable[[httpx.Request], httpx.Response],
) -> tuple[HttpGoogleOAuthClient, list[httpx.Request]]:
    """回傳用假網路的 client，以及它送出的請求清單。"""
    sent: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return handler(request)

    client = HttpGoogleOAuthClient(
        "test-client-id", CLIENT_SECRET, transport=httpx.MockTransport(record)
    )
    return client, sent


def form(request: httpx.Request) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(request.content.decode()).items()}


# ---- 導向 Google 的網址 ----


def test_login_asks_only_for_basic_profile_and_lets_the_user_choose_an_account() -> (
    None
):
    q = query(login_url(client_id="cid", redirect_uri=REDIRECT_URI, state="s1"))
    assert q["scope"] == "openid email profile"
    assert q["prompt"] == "select_account"
    assert q["response_type"] == "code"
    assert q["redirect_uri"] == REDIRECT_URI
    assert q["state"] == "s1"
    assert "access_type" not in q  # 登入不拿 refresh token


@pytest.mark.parametrize("scope", [DRIVE_SCOPE, GMAIL_SCOPE])
def test_authorization_asks_the_logged_in_account_for_offline_access(
    scope: str,
) -> None:
    q = query(
        authorization_url(
            client_id="cid",
            redirect_uri=REDIRECT_URI,
            state="s2",
            scope=scope,
            login_hint="carol@example.com",
        )
    )
    assert q["scope"] == f"openid {scope}"
    assert q["login_hint"] == "carol@example.com"
    assert q["include_granted_scopes"] == "true"
    assert q["access_type"] == "offline"
    assert q["prompt"] == "consent"
    assert q["state"] == "s2"


# ---- id_token ----


def test_id_token_claims_are_read() -> None:
    identity = decode_id_token(
        make_id_token(
            sub="123", email="carol@example.com", email_verified=True, name="Carol"
        )
    )
    assert identity.sub == "123"
    assert identity.email == "carol@example.com"
    assert identity.email_verified is True
    assert identity.name == "Carol"


def test_id_token_without_email_still_gives_the_account() -> None:
    # 授權時使用者只同意 openid：沒有 email，但 sub 還在，用來比對是不是同一個帳號
    identity = decode_id_token(make_id_token(sub="123"))
    assert identity.sub == "123"
    assert identity.email is None
    assert identity.email_verified is False


def test_email_is_unverified_unless_google_says_so() -> None:
    assert not decode_id_token(make_id_token(sub="1", email="a@b.com")).email_verified
    assert not decode_id_token(
        make_id_token(sub="1", email="a@b.com", email_verified=False)
    ).email_verified


@pytest.mark.parametrize(
    "token", ["", "only-one-part", "a.!!!.c", make_id_token(email="a@b.com")]
)
def test_malformed_id_token_is_rejected(token: str) -> None:
    with pytest.raises(GoogleOAuthError):
        decode_id_token(token)


# ---- 用授權碼換 token ----


async def test_exchange_code_returns_tokens_scopes_and_identity() -> None:
    id_token = make_id_token(sub="123", email="carol@example.com", email_verified=True)
    client, sent = make_client(
        lambda _: httpx.Response(
            200,
            json={
                "access_token": "at",
                "refresh_token": "rt",
                "scope": f"openid {DRIVE_SCOPE}",
                "id_token": id_token,
            },
        )
    )
    result = await client.exchange_code("the-code", REDIRECT_URI)

    assert result.access_token == "at"
    assert result.refresh_token == "rt"
    assert result.scopes == ("openid", DRIVE_SCOPE)
    assert result.identity is not None and result.identity.sub == "123"
    body = form(sent[0])
    assert body["grant_type"] == "authorization_code"
    assert body["code"] == "the-code"
    assert body["redirect_uri"] == REDIRECT_URI


async def test_exchange_code_error_does_not_leak_the_client_secret() -> None:
    client, _ = make_client(
        lambda _: httpx.Response(
            400, json={"error": "invalid_grant", "detail": CLIENT_SECRET}
        )
    )
    with pytest.raises(GoogleOAuthError) as excinfo:
        await client.exchange_code("bad-code", REDIRECT_URI)
    assert "invalid_grant" in str(excinfo.value)
    assert CLIENT_SECRET not in str(excinfo.value)


# ---- 換發 access token ----


async def test_refresh_returns_a_new_access_token() -> None:
    client, sent = make_client(
        lambda _: httpx.Response(200, json={"access_token": "new-at"})
    )
    assert await client.refresh_access_token("rt") == "new-at"
    assert form(sent[0])["grant_type"] == "refresh_token"


async def test_refresh_reports_an_expired_or_revoked_grant() -> None:
    client, _ = make_client(
        lambda _: httpx.Response(400, json={"error": "invalid_grant"})
    )
    with pytest.raises(InvalidGrantError):
        await client.refresh_access_token("old-rt")


async def test_refresh_reports_other_errors_differently() -> None:
    client, _ = make_client(lambda _: httpx.Response(500, text="oops"))
    with pytest.raises(GoogleOAuthError) as excinfo:
        await client.refresh_access_token("rt")
    assert not isinstance(excinfo.value, InvalidGrantError)


# ---- 撤銷 ----


async def test_revoke_sends_the_token_to_google() -> None:
    client, sent = make_client(lambda _: httpx.Response(200, json={}))
    await client.revoke("rt")
    assert form(sent[0]) == {"token": "rt"}


async def test_revoking_an_already_invalid_token_is_fine() -> None:
    client, _ = make_client(
        lambda _: httpx.Response(400, json={"error": "invalid_token"})
    )
    await client.revoke("gone")


# ---- Drive 資料夾 ----


async def test_create_drive_folder_returns_its_id() -> None:
    client, sent = make_client(lambda _: httpx.Response(200, json={"id": "folder-1"}))
    assert await client.create_drive_folder("at", "好險有你") == "folder-1"
    request = sent[0]
    assert request.headers["Authorization"] == "Bearer at"
    assert json.loads(request.content) == {
        "name": "好險有你",
        "mimeType": DRIVE_FOLDER_MIME_TYPE,
    }
