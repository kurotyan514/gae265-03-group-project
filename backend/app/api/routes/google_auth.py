"""Google 登入與授權（ADR-0020）。

登入：/auth/google/login 產生 state 存進 session，導向 Google → 使用者選帳號 →
Google 導回 /auth/google/callback，比對 state、用 code 換使用者資料、確認 email 已驗證 →
建立或更新使用者並發 session → 導回 next（只接受站內路徑）。失敗導回 /login?error=<原因>。

授權（Drive、Gmail）：已用 Google 登入的使用者到 /auth/google/authorize，導向 Google 時帶
login_hint → 同一個 callback 依 session 記的目的分流：比對 state 與登入的使用者、
比對 Google 帳號的 sub、加密保存 refresh token 與實際拿到的 scope、第一次授權 Drive 時建資料夾 →
導回 next 並加上 google_auth=<結果>。

token 與使用者資料不進 log。
"""

import logging
import secrets
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlmodel import select

from app.api.deps import CurrentUser, GoogleOAuthDep, SessionDep
from app.core.auth import upsert_user
from app.core.config import settings
from app.core.google_grants import fresh_access_token, grant_of, is_usable, revoke_grant
from app.core.google_oauth import (
    DRIVE_SCOPE,
    GMAIL_SCOPE,
    GoogleOAuthClient,
    GoogleOAuthError,
    TokenResponse,
    authorization_url,
    login_url,
)
from app.core.token_cipher import cipher_from_settings
from app.models import GoogleGrant, Identity

router = APIRouter(prefix="/auth/google", tags=["auth"])
# 只記 Google 的錯誤代碼與使用者的 UUID，不記 token、email 或其他個資（ADR-0009）
logger = logging.getLogger(__name__)

# 存在 session 裡、這次導向 Google 的資料（state、目的、之後要回去的頁面）
PENDING_KEY = "google_oauth"

LoginError = Literal["cancelled", "state_mismatch", "google_failed", "email_unverified"]

Purpose = Literal["drive", "gmail"]
SCOPE_FOR: dict[str, str] = {"drive": DRIVE_SCOPE, "gmail": GMAIL_SCOPE}
# 授權完導回 next 時附上的 google_auth=<結果>，由前端顯示訊息
AuthorizeResult = Literal[
    "granted",
    "cancelled",
    "account_mismatch",
    "google_failed",
    "state_mismatch",
    "not_google_login",
]

# 系統在使用者 Google Drive 建立的資料夾名稱；6 號把理賠文件存進去
DRIVE_FOLDER_NAME = "好險有你 理賠文件"


def redirect_uri() -> str:
    """Google 導回的網址：由 PUBLIC_BASE_URL 組成，不從請求的 Host 推（經 Vite proxy 時 Host 不對）。"""
    assert settings.PUBLIC_BASE_URL is not None
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}{settings.API_V1_STR}/auth/google/callback"


def safe_next_path(next_path: str | None) -> str:
    """只接受站內路徑，避免登入完被導到外部網站。"""
    if (
        not next_path
        or not next_path.startswith("/")
        or next_path.startswith("//")
        or "\\" in next_path
    ):
        return "/"
    return next_path


def login_failed(error: LoginError) -> RedirectResponse:
    return RedirectResponse(f"/login?error={error}", status_code=302)


def authorize_done(next_path: str, result: AuthorizeResult) -> RedirectResponse:
    """導回 next，保留它原本的網址參數，再加上 google_auth=<結果>。"""
    parts = urlsplit(safe_next_path(next_path))
    query = [(k, v) for k, v in parse_qsl(parts.query) if k != "google_auth"]
    query.append(("google_auth", result))
    return RedirectResponse(
        urlunsplit(("", "", parts.path, urlencode(query), parts.fragment)),
        status_code=302,
    )


async def google_identity_of(
    session: SessionDep, user_id: uuid.UUID
) -> Identity | None:
    return (
        await session.exec(
            select(Identity).where(
                Identity.user_id == user_id, Identity.provider == "google"
            )
        )
    ).first()


@router.get("/login", response_class=RedirectResponse, status_code=302)
async def google_login(
    request: Request,
    _: GoogleOAuthDep,  # 設定不完整時在這裡回 503
    next_path: Annotated[
        str | None, Query(alias="next", description="登入後要回到的站內路徑")
    ] = None,
) -> RedirectResponse:
    assert settings.GOOGLE_CLIENT_ID is not None
    state = secrets.token_urlsafe(32)
    request.session[PENDING_KEY] = {
        "state": state,
        "purpose": "login",
        "next": safe_next_path(next_path),
    }
    url = login_url(
        client_id=settings.GOOGLE_CLIENT_ID, redirect_uri=redirect_uri(), state=state
    )
    return RedirectResponse(url, status_code=302)


@router.get("/authorize", response_class=RedirectResponse, status_code=302)
async def google_authorize(
    request: Request,
    session: SessionDep,
    user: CurrentUser,  # 沒登入回 401
    _: GoogleOAuthDep,  # 設定不完整時回 503
    purpose: Annotated[
        Purpose, Query(description="drive：存理賠文件；gmail：建立草稿與寄信")
    ],
    next_path: Annotated[
        str | None, Query(alias="next", description="授權後要回到的站內路徑")
    ] = None,
) -> RedirectResponse:
    back_to = safe_next_path(next_path)
    identity = await google_identity_of(session, user.id)
    if identity is None:
        # 測試登入的帳號沒有 Google 帳號可以比對
        return authorize_done(back_to, "not_google_login")
    assert settings.GOOGLE_CLIENT_ID is not None
    state = secrets.token_urlsafe(32)
    request.session[PENDING_KEY] = {
        "state": state,
        "purpose": purpose,
        "next": back_to,
        "user_id": str(user.id),
    }
    url = authorization_url(
        client_id=settings.GOOGLE_CLIENT_ID,
        redirect_uri=redirect_uri(),
        state=state,
        scope=SCOPE_FOR[purpose],
        login_hint=identity.provider_email or user.email,
    )
    return RedirectResponse(url, status_code=302)


@router.get("/callback", response_class=RedirectResponse, status_code=302)
async def google_callback(
    request: Request,
    session: SessionDep,
    google: GoogleOAuthDep,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """登入與授權共用的 Google 導回網址，依 session 記的目的分流。"""
    # state 只能用一次：不論成功與否都先拿掉
    pending = request.session.pop(PENDING_KEY, None)
    if not isinstance(pending, dict):
        return login_failed("state_mismatch")
    state_ok = bool(state) and secrets.compare_digest(
        str(pending.get("state", "")), state or ""
    )
    if pending.get("purpose") in SCOPE_FOR:
        return await _finish_authorization(
            request, session, google, pending, state_ok, code, error
        )
    return await _finish_login(request, session, google, pending, state_ok, code, error)


async def _finish_login(
    request: Request,
    session: SessionDep,
    google: GoogleOAuthClient,
    pending: dict[str, Any],
    state_ok: bool,
    code: str | None,
    error: str | None,
) -> RedirectResponse:
    if not state_ok:
        return login_failed("state_mismatch")
    if error or not code:
        return login_failed("cancelled")  # 使用者在 Google 按了取消
    try:
        tokens = await google.exchange_code(code, redirect_uri())
    except GoogleOAuthError as exc:
        logger.warning("Google 登入換 token 失敗：%s", exc)
        return login_failed("google_failed")
    identity = tokens.identity
    if identity is None or identity.email is None:
        logger.warning("Google 登入沒有拿到使用者的 email")
        return login_failed("google_failed")
    if not identity.email_verified:
        # 後台用 email 判斷管理者（ADR-0016），未驗證的 email 可能被冒用
        return login_failed("email_unverified")

    user = await upsert_user(
        session,
        "google",
        identity.sub,
        identity.email.lower(),
        identity.name,
        email_verified=True,
    )
    request.session.clear()  # 換一個新的 session，避免沿用登入前的內容
    request.session["user_id"] = str(user.id)
    return RedirectResponse(str(pending.get("next") or "/"), status_code=302)


async def _finish_authorization(
    request: Request,
    session: SessionDep,
    google: GoogleOAuthClient,
    pending: dict[str, Any],
    state_ok: bool,
    code: str | None,
    error: str | None,
) -> RedirectResponse:
    back_to = str(pending.get("next") or "/")
    # 開始授權的人和現在登入的人必須是同一位
    if not state_ok or request.session.get("user_id") != pending.get("user_id"):
        return authorize_done(back_to, "state_mismatch")
    if error or not code:
        return authorize_done(back_to, "cancelled")
    user_id = uuid.UUID(str(pending["user_id"]))
    identity = await google_identity_of(session, user_id)
    if identity is None:
        return authorize_done(back_to, "not_google_login")
    try:
        tokens = await google.exchange_code(code, redirect_uri())
    except GoogleOAuthError as exc:
        logger.warning("Google 授權換 token 失敗：user=%s %s", user_id, exc)
        return authorize_done(back_to, "google_failed")
    if tokens.identity is None or tokens.identity.sub != identity.provider_user_id:
        # 使用者在授權畫面換成了別的 Google 帳號：什麼都不存
        return authorize_done(back_to, "account_mismatch")

    requested = SCOPE_FOR[str(pending["purpose"])]
    if requested not in tokens.scopes:
        # 沒拿到要的權限：對使用者來說就是沒有同意，一律當成取消（使用者只需要選同意或取消）。
        # 這時 Google 可能只給 openid，沒有 refresh token、id_token 也沒有 email，
        # 所以先看權限，才不會被誤報成 Google 失敗。有 refresh token 時照樣記下實際拿到的 scope
        if tokens.refresh_token is not None:
            await _save_grant(session, user_id, tokens)
        return authorize_done(back_to, "cancelled")
    grant = await _save_grant(session, user_id, tokens)
    if grant is None:
        logger.warning("Google 授權沒有給 refresh token：user=%s", user_id)
        return authorize_done(back_to, "google_failed")
    if requested == DRIVE_SCOPE and grant.drive_folder_id is None:
        try:
            grant.drive_folder_id = await google.create_drive_folder(
                tokens.access_token, DRIVE_FOLDER_NAME
            )
        except GoogleOAuthError as exc:
            # 授權已經存好；下次重新授權 Drive 時會再建一次資料夾
            logger.warning("建立 Drive 資料夾失敗：user=%s %s", user_id, exc)
            return authorize_done(back_to, "google_failed")
        session.add(grant)
        await session.commit()
    return authorize_done(back_to, "granted")


async def _save_grant(
    session: SessionDep, user_id: uuid.UUID, tokens: TokenResponse
) -> GoogleGrant | None:
    """保存加密後的 refresh token 與實際拿到的 scope；一位使用者一筆，重新授權時更新。"""
    grant = await grant_of(session, user_id)
    now = datetime.now(UTC)
    if tokens.refresh_token is None:
        # 照理 prompt=consent 一定會給；沒給時只能沿用原本有效的授權
        if grant is None or grant.refresh_token_encrypted is None:
            return None
    else:
        cipher = cipher_from_settings()
        if grant is None:
            grant = GoogleGrant(user_id=user_id, granted_at=now)
        grant.refresh_token_encrypted = cipher.encrypt(tokens.refresh_token)
        grant.key_version = cipher.key_version
        grant.status = "active"
        grant.granted_at = now
        grant.revoked_at = None
    grant.scopes = list(tokens.scopes)
    session.add(grant)
    await session.commit()
    await session.refresh(grant)
    return grant


class GoogleGrantOut(BaseModel):
    status: Literal["none", "active", "revoked", "invalid"] = Field(
        description="none：沒授權過；revoked：使用者取消了；invalid：過期或在 Google 被撤銷，要重新授權"
    )
    drive: bool = Field(description="現在可以存理賠文件到使用者的 Google Drive")
    gmail: bool = Field(description="現在可以用使用者的 Gmail 建立草稿與寄信")


@router.get("/grant")
async def google_grant_status(
    session: SessionDep, user: CurrentUser, google: GoogleOAuthDep
) -> GoogleGrantOut:
    """目前的 Google 授權。授權有效時會實際向 Google 換一次 token 確認沒有過期。"""
    grant = await grant_of(session, user.id)
    if grant is None:
        return GoogleGrantOut(status="none", drive=False, gmail=False)
    if grant.status == "active":
        try:
            await fresh_access_token(session, grant, google)
        except GoogleOAuthError:
            pass  # Google 暫時連不上：不把授權誤判成失效
    usable = is_usable(grant)
    return GoogleGrantOut(
        status=grant.status,  # pyright: ignore[reportArgumentType]
        drive=usable and DRIVE_SCOPE in grant.scopes,
        gmail=usable and GMAIL_SCOPE in grant.scopes,
    )


@router.post("/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def google_revoke(
    session: SessionDep, user: CurrentUser, google: GoogleOAuthDep
) -> Response:
    """取消 Google 授權：清空 token、保留紀錄。已存進 Drive 的文件與 Gmail 的草稿不動。"""
    grant = await grant_of(session, user.id)
    if grant is not None:
        await revoke_grant(session, grant, google)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
