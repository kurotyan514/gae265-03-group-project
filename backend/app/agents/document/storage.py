"""存到使用者 Google Drive 的理賠資料夾（#70、ADR-0021）。

- 理賠資料夾「旅遊保險理賠」由平台在使用者授權後建立、編號存在 `google_grant.drive_folder_id`，
  經 `GoogleAccess` 交給 6 號（#71）。平台還沒提供前，6 號自己找或建同名資料夾
  （`drive.file` 只看得到本應用程式建立的檔案，所以找到的一定是我們建的）。
- 每個事件一個子資料夾，名稱是事件編號；檔名由程式產生，不含個資。
- `storage_path` 存 Drive 檔案編號。6 號不提供取檔，7 號自己用編號取。
"""

import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Protocol, cast

import httpx

from app.contracts import GoogleAccess, UserContext

DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"
ROOT_FOLDER_NAME = "旅遊保險理賠"
FOLDER_MIME = "application/vnd.google-apps.folder"
_EXTENSIONS = {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png"}


class StorageFailed(Exception):
    """存檔失敗；訊息不含檔案內容。"""


class DriveStorage(Protocol):
    async def ensure_folder(self, token: str, name: str, parent_id: str | None) -> str:
        """找同名資料夾，沒有就建立；回傳資料夾編號。"""
        ...

    async def upload(
        self, token: str, folder_id: str, name: str, content: bytes, content_type: str
    ) -> str:
        """上傳檔案，回傳 Drive 檔案編號。"""
        ...


def stored_file_name(code: str, part: str, content_type: str) -> str:
    """程式產生的檔名：文件代碼＋種類＋隨機碼，不含使用者的原檔名與個資。"""
    return f"{code}-{part}-{uuid.uuid4().hex[:8]}{_EXTENSIONS.get(content_type, '')}"


async def claim_folder_id(
    google: GoogleAccess, user: UserContext, drive: DriveStorage, token: str
) -> str:
    """理賠資料夾的編號：平台有提供就用平台的（#71），否則自己找或建。"""
    provided = getattr(google, "drive_folder_id", None)
    if callable(provided):
        lookup = cast(Callable[[UserContext], Awaitable[str | None]], provided)
        folder_id = await lookup(user)
        if folder_id:
            return folder_id
    return await drive.ensure_folder(token, ROOT_FOLDER_NAME, None)


class GoogleDrive:
    """Google Drive v3 REST。`transport` 給測試換成假的，不連網。"""

    API = "https://www.googleapis.com/drive/v3/files"
    UPLOAD = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.transport = transport

    def _client(self, token: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self.transport,
            timeout=30.0,
            headers={"Authorization": f"Bearer {token}"},
        )

    async def ensure_folder(self, token: str, name: str, parent_id: str | None) -> str:
        escaped = name.replace("\\", "\\\\").replace("'", "\\'")
        query = f"name = '{escaped}' and mimeType = '{FOLDER_MIME}' and trashed = false"
        if parent_id:
            query += f" and '{parent_id}' in parents"
        try:
            async with self._client(token) as client:
                found = await client.get(
                    self.API,
                    params={"q": query, "fields": "files(id)", "spaces": "drive"},
                )
                found.raise_for_status()
                files = found.json().get("files", [])
                if files:
                    return files[0]["id"]
                metadata: dict[str, object] = {"name": name, "mimeType": FOLDER_MIME}
                if parent_id:
                    metadata["parents"] = [parent_id]
                created = await client.post(
                    self.API, params={"fields": "id"}, json=metadata
                )
                created.raise_for_status()
                return created.json()["id"]
        except (httpx.HTTPError, KeyError, ValueError) as e:
            raise StorageFailed(f"建立雲端資料夾失敗（{type(e).__name__}）") from e

    async def upload(
        self, token: str, folder_id: str, name: str, content: bytes, content_type: str
    ) -> str:
        boundary = uuid.uuid4().hex
        metadata = json.dumps({"name": name, "parents": [folder_id]})
        body = (
            (
                f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
                f"{metadata}\r\n--{boundary}\r\nContent-Type: {content_type}\r\n\r\n"
            ).encode()
            + content
            + f"\r\n--{boundary}--\r\n".encode()
        )
        try:
            async with self._client(token) as client:
                response = await client.post(
                    self.UPLOAD,
                    content=body,
                    headers={"Content-Type": f"multipart/related; boundary={boundary}"},
                )
                response.raise_for_status()
                return response.json()["id"]
        except (httpx.HTTPError, KeyError, ValueError) as e:
            raise StorageFailed(f"上傳雲端失敗（{type(e).__name__}）") from e
