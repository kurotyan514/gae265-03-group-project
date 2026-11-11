"""後端和 Google OAuth 的對話（ADR-0020）。

集中在這裡，呼叫端只依賴 `GoogleOAuthClient` 這個 Protocol：正式執行用 `HttpGoogleOAuthClient`，
測試換成假的，不連 Google。錯誤訊息只帶 Google 的錯誤代碼，不帶 token、client secret 或使用者資料。
"""

import base64
import binascii
import json
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlencode

import httpx

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"

LOGIN_SCOPES = ("openid", "email", "profile")
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"
GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.compose"
# 授權 Drive 時在使用者的 Drive 建立的理賠文件資料夾；6 號一律用 GoogleAccess.drive_folder_id，不寫死名稱
DRIVE_FOLDER_NAME = "好險有你 理賠文件"

DRIVE_FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"


class GoogleOAuthError(Exception):
    """Google 回應錯誤或格式不對。"""


class InvalidGrantError(GoogleOAuthError):
    """refresh token 已失效或被撤銷（invalid_grant），要請使用者重新授權。"""


@dataclass(frozen=True)
class GoogleIdentity:
    """id_token 裡我們用到的欄位。sub 是 Google 帳號的穩定識別；email 可能會變。

    email 只有在這次授權包含 email scope 時才有：登入一定有；授權時 Google 有時只給 openid，
    就沒有 email，這時只用 sub 比對帳號。
    """

    sub: str
    email: str | None
    email_verified: bool
    name: str | None = None


@dataclass(frozen=True)
class TokenResponse:
    access_token: str
    refresh_token: str | None
    scopes: tuple[str, ...]
    identity: GoogleIdentity | None


class GoogleOAuthClient(Protocol):
    async def exchange_code(self, code: str, redirect_uri: str) -> TokenResponse: ...

    async def refresh_access_token(self, refresh_token: str) -> str: ...

    async def revoke(self, token: str) -> None: ...

    async def create_drive_folder(self, access_token: str, name: str) -> str: ...


def login_url(*, client_id: str, redirect_uri: str, state: str) -> str:
    """登入：只要基本資料，並讓使用者選帳號。"""
    return _authorize_url(
        client_id=client_id,
        redirect_uri=redirect_uri,
        state=state,
        scopes=LOGIN_SCOPES,
        prompt="select_account",
    )


def authorization_url(
    *, client_id: str, redirect_uri: str, state: str, scope: str, login_hint: str
) -> str:
    """授權 Drive 或 Gmail：對著登入的帳號詢問、保留已授權的 scope、要 refresh token。

    多要 openid，callback 才拿得到 id_token 比對是不是同一個帳號；prompt=consent 確保 Google
    每次都發 refresh token（授權過期後重新授權時也需要）。
    """
    return _authorize_url(
        client_id=client_id,
        redirect_uri=redirect_uri,
        state=state,
        scopes=("openid", scope),
        prompt="consent",
        login_hint=login_hint,
        access_type="offline",
        include_granted_scopes="true",
    )


def _authorize_url(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    scopes: tuple[str, ...],
    prompt: str,
    **extra: str,
) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
        "prompt": prompt,
        **extra,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def decode_id_token(id_token: str) -> GoogleIdentity:
    """讀 id_token 的內容。

    不驗簽章：id_token 是後端用 client secret 經 HTTPS 直接向 Google 的 token 端點換來的，
    中間沒有經過瀏覽器，Google 的文件說明這種情況可以信任它的內容。
    """
    try:
        payload = id_token.split(".")[1]
        claims: dict[str, Any] = json.loads(
            base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        )
        email = claims.get("email")
        return GoogleIdentity(
            sub=str(claims["sub"]),
            email=str(email) if email else None,
            email_verified=bool(email) and claims.get("email_verified") is True,
            name=claims.get("name"),
        )
    except (IndexError, KeyError, ValueError, binascii.Error) as exc:
        raise GoogleOAuthError("id_token 格式不對") from exc


class HttpGoogleOAuthClient:
    """真的連 Google。transport 只給測試注入假的網路用。"""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._transport = transport
        self._timeout = timeout

    def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self._transport, timeout=self._timeout)

    async def exchange_code(self, code: str, redirect_uri: str) -> TokenResponse:
        async with self._http() as http:
            response = await http.post(
                TOKEN_URL,
                data={
                    "code": code,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
        data = _json_or_error(response)
        try:
            id_token = data.get("id_token")
            return TokenResponse(
                access_token=str(data["access_token"]),
                refresh_token=data.get("refresh_token"),
                scopes=tuple(str(data.get("scope", "")).split()),
                identity=decode_id_token(id_token) if id_token else None,
            )
        except KeyError as exc:
            raise GoogleOAuthError("token 回應缺少 access_token") from exc

    async def refresh_access_token(self, refresh_token: str) -> str:
        async with self._http() as http:
            response = await http.post(
                TOKEN_URL,
                data={
                    "refresh_token": refresh_token,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "grant_type": "refresh_token",
                },
            )
        if response.status_code == 400 and _error_code(response) == "invalid_grant":
            raise InvalidGrantError("refresh token 已失效")
        data = _json_or_error(response)
        try:
            return str(data["access_token"])
        except KeyError as exc:
            raise GoogleOAuthError("token 回應缺少 access_token") from exc

    async def revoke(self, token: str) -> None:
        async with self._http() as http:
            response = await http.post(REVOKE_URL, data={"token": token})
        # 已經失效或被撤銷的 token 會回 invalid_token：結果一樣是撤銷了
        if response.status_code == 400 and _error_code(response) == "invalid_token":
            return
        _json_or_error(response)

    async def create_drive_folder(self, access_token: str, name: str) -> str:
        async with self._http() as http:
            response = await http.post(
                DRIVE_FILES_URL,
                params={"fields": "id"},
                headers={"Authorization": f"Bearer {access_token}"},
                json={"name": name, "mimeType": DRIVE_FOLDER_MIME_TYPE},
            )
        data = _json_or_error(response)
        try:
            return str(data["id"])
        except KeyError as exc:
            raise GoogleOAuthError("Drive 回應缺少資料夾 id") from exc


def _error_code(response: httpx.Response) -> str | None:
    try:
        error = response.json().get("error")
    except ValueError:
        return None
    # OAuth 端點回字串；Drive 等 API 回 {"code": ..., "status": ...}
    if isinstance(error, dict):
        return str(error.get("status") or error.get("code"))
    return str(error) if error else None


def _json_or_error(response: httpx.Response) -> dict[str, Any]:
    if response.is_error:
        raise GoogleOAuthError(
            f"Google 回應 {response.status_code}（{_error_code(response) or '沒有錯誤代碼'}）"
        )
    try:
        data = response.json()
    except ValueError as exc:
        raise GoogleOAuthError("Google 回應不是 JSON") from exc
    if not isinstance(data, dict):
        raise GoogleOAuthError("Google 回應格式不對")
    return data
