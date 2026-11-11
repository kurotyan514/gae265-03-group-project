"""7 號真的連 Google 的轉接器：Drive v3 取檔、Gmail API 寄信與建立草稿（規格「模組」）。

只做薄薄一層 HTTP 呼叫，把 Google 的錯誤換成錯誤類別。`transport` 給測試換成假的網路，
不寫連真的 Google 的自動測試（ADR-0020），真的寄送用測試帳號手動確認。
"""

from urllib.parse import quote

import httpx

from app.agents.package.google_api import (
    DriveFile,
    DriveFileStatus,
    GoogleApiError,
    GoogleErrorKind,
)

DRIVE_FILES = "https://www.googleapis.com/drive/v3/files"
GMAIL_SEND = "https://gmail.googleapis.com/upload/gmail/v1/users/me/messages/send"
GMAIL_DRAFTS = "https://gmail.googleapis.com/upload/gmail/v1/users/me/drafts"


def _kind(status_code: int) -> GoogleErrorKind:
    if status_code == 404:
        return "not_found"
    if status_code in (401, 403):
        return "unauthorized"
    return "unavailable"


class HttpGoogleApi:
    def __init__(
        self, transport: httpx.AsyncBaseTransport | None = None, timeout: float = 30.0
    ) -> None:
        self._transport = transport
        self._timeout = timeout

    def _client(self, token: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self._transport,
            timeout=self._timeout,
            headers={"Authorization": f"Bearer {token}"},
        )

    async def file_status(self, token: str, file_id: str) -> DriveFileStatus:
        url = f"{DRIVE_FILES}/{quote(file_id, safe='')}"
        try:
            async with self._client(token) as client:
                metadata = await client.get(url, params={"fields": "trashed"})
            if metadata.status_code == 404:
                return "not_found"
            if metadata.is_error:
                raise GoogleApiError(_kind(metadata.status_code))
            return "trashed" if metadata.json().get("trashed") is True else "ok"
        except (httpx.HTTPError, ValueError, TypeError, AttributeError) as error:
            raise GoogleApiError("unavailable") from error

    async def fetch_file(self, token: str, file_id: str) -> DriveFile:
        # 檔案編號整段編碼，避免奇怪的編號改到別的網址
        url = f"{DRIVE_FILES}/{quote(file_id, safe='')}"
        try:
            async with self._client(token) as client:
                metadata = await client.get(
                    url, params={"fields": "name,mimeType,trashed"}
                )
                if metadata.is_error:
                    raise GoogleApiError(_kind(metadata.status_code))
                info = metadata.json()
                if info.get("trashed") is True:
                    raise GoogleApiError("trashed")
                media = await client.get(url, params={"alt": "media"})
                if media.is_error:
                    raise GoogleApiError(_kind(media.status_code))
                return DriveFile(
                    name=str(info["name"]),
                    mime_type=str(info.get("mimeType") or "application/octet-stream"),
                    content=media.content,
                )
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as error:
            # 錯誤訊息只放錯誤類別，不放 token 或檔案內容
            raise GoogleApiError("unavailable") from error

    async def send_message(self, token: str, message: bytes) -> str:
        return await self._upload(GMAIL_SEND, token, message)

    async def create_draft(self, token: str, message: bytes) -> str:
        # 回傳的是草稿編號（drafts.create 的 id），不是草稿裡那封信的編號
        return await self._upload(GMAIL_DRAFTS, token, message)

    async def _upload(self, url: str, token: str, message: bytes) -> str:
        # 用上傳的寫法把整封信原樣送出：附件大也寄得出去，不用轉 base64 放進 JSON
        try:
            async with self._client(token) as client:
                response = await client.post(
                    url,
                    params={"uploadType": "media"},
                    headers={"Content-Type": "message/rfc822"},
                    content=message,
                )
            if response.is_error:
                kind = _kind(response.status_code)
                raise GoogleApiError("unavailable" if kind == "not_found" else kind)
            return str(response.json()["id"])
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as error:
            raise GoogleApiError("unavailable") from error
