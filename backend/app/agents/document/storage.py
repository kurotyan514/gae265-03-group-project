"""存到使用者 Google Drive 的理賠資料夾（#70、ADR-0021）。

- 理賠資料夾「旅遊保險理賠」由平台在使用者授權後建立、編號存在 `google_grant.drive_folder_id`，
  經 `GoogleAccess` 交給 6 號（#71）。平台還沒提供前，6 號自己找或建同名資料夾
  （`drive.file` 只看得到本應用程式建立的檔案，所以找到的一定是我們建的）。
- 資料夾分兩層：行程（「日本 2026-07-05～07-10」）→ 事故（「班機延誤 2026-07-10」）。
  理賠申請書整趟行程共用一份，放在行程那層。資料夾名稱只有目的地、日期與事故類型，不含姓名。
- 檔名照規格書 R8：「事故類型_待辦名稱_序號」，例如「班機延誤_航空公司開立班機延誤／取消證明_1.pdf」；
  理賠申請書是「理賠申請書_1.pdf」。待辦名稱去掉開頭的「請」「保留」等動詞。不用使用者的原檔名。
- `storage_path` 存 Drive 檔案編號。6 號不提供取檔，7 號自己用編號取。
"""

import json
import re
import uuid
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Protocol, cast

import httpx

from app.contracts import GoogleAccess, IncidentContext, TodoView, UserContext

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


CLAIM_FORM_CODE = "D10"  # 理賠申請書：整趟行程一項，放在行程資料夾
CLAIM_FORM_NAME = "理賠申請書"
_LEADING_VERB = re.compile(r"^(請|向|取得|保留|保存|準備|填寫|列印)")
_UNSAFE = re.compile(r"[/\\:*?\"<>|\n\r\t]")


def _clean(text: str, limit: int = 40) -> str:
    """資料夾與檔名不能有斜線等字元；過長的截斷。"""
    return _UNSAFE.sub("／", text).strip()[:limit]


def _range(start: date | None, end: date | None) -> str:
    if start and end:
        tail = end.strftime("%m-%d") if start.year == end.year else end.isoformat()
        return f"{start.isoformat()}～{tail}"
    one = start or end
    return one.isoformat() if one else ""


def trip_folder_name(ctx: IncidentContext) -> str:
    """行程資料夾：目的地＋保險期間，例如「日本 2026-07-05～07-10」。"""
    parts = [ctx.destination or "", _range(ctx.policy.start_date, ctx.policy.end_date)]
    return _clean(" ".join(p for p in parts if p)) or "行程"


def incident_folder_name(ctx: IncidentContext) -> str:
    """事故資料夾：事故類型＋發生日期，例如「班機延誤 2026-07-10」。"""
    when = ctx.occurred_at.date().isoformat() if ctx.occurred_at else ""
    parts = [ctx.incident_type_name or "事故", when]
    return _clean(" ".join(p for p in parts if p))


def document_file_name(
    ctx: IncidentContext, code: str, todo: TodoView, content_type: str
) -> str:
    """規格書 R8 的檔名「事故類型_待辦名稱_序號」；序號是這項待辦已存的文件數加一。"""
    seq = 1 + sum(
        1
        for d in ctx.documents
        if d.todo_id == todo.id and d.recognition_status == "recognized"
    )
    ext = _EXTENSIONS.get(content_type, "")
    if code == CLAIM_FORM_CODE:
        return f"{CLAIM_FORM_NAME}_{seq}{ext}"
    kind = _clean(ctx.incident_type_name or "事故")
    title = _clean(_LEADING_VERB.sub("", todo.title), 60)
    return f"{kind}_{title}_{seq}{ext}"


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


class DevFakeDrive:
    """開發與展示用的假雲端（DOCUMENT_DEV_FAKE_STORAGE）：不連網、不保存檔案內容，只回傳假的檔案編號。

    `saved` 記下每次存檔的「資料夾路徑／檔名」，給測試與展示看結構，不含檔案內容。
    """

    def __init__(self) -> None:
        self._names: dict[str, str] = {}
        self.saved: list[str] = []

    async def ensure_folder(self, token: str, name: str, parent_id: str | None) -> str:
        path = f"{self._names.get(parent_id or '', '')}/{name}".lstrip("/")
        folder_id = f"dev-fake-folder-{uuid.uuid5(uuid.NAMESPACE_URL, path).hex[:12]}"
        self._names[folder_id] = path
        return folder_id

    async def upload(
        self, token: str, folder_id: str, name: str, content: bytes, content_type: str
    ) -> str:
        self.saved.append(f"{self._names.get(folder_id, '')}/{name}")
        return f"dev-fake-file-{uuid.uuid4().hex[:12]}"


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
