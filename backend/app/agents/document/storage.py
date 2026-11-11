"""存到使用者 Google Drive 的理賠資料夾（#70、ADR-0021）。

- 理賠資料夾「好險有你 理賠文件」由平台在使用者授權後建立、編號存在 `google_grant.drive_folder_id`，
  經 `GoogleAccess` 交給 6 號（#71）。平台還沒提供前，6 號自己找或建同名資料夾
  （`drive.file` 只看得到本應用程式建立的檔案，所以找到的一定是我們建的）。
- 資料夾分兩層：行程（「日本 2026-07-05～07-10」）→ 事故（「班機延誤 2026-07-10」）。
  理賠申請書整趟行程共用一份，放在行程那層。資料夾名稱只有目的地、日期與事故類型，不含姓名。
- 檔名照規格書 R8：「事故類型_待辦名稱_序號」，例如「班機延誤_航空公司開立班機延誤／取消證明_1.pdf」；
  理賠申請書是「理賠申請書_1.pdf」。待辦名稱去掉開頭的「請」「保留」等動詞。不用使用者的原檔名。
- 「不確定」的文件也先存（契約 v2，使用者確認時沿用），放在事故資料夾，檔名「班機延誤_待確認_1.pdf」。
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
# 和平台建的資料夾同名（app.core.google_oauth.DRIVE_FOLDER_NAME）；只在平台沒給編號時備用
ROOT_FOLDER_NAME = "好險有你 理賠文件"
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

    async def rename(self, token: str, file_id: str, name: str) -> None:
        """把已存的檔案改名（不換資料夾、不換內容）。"""
        ...

    async def download(self, token: str, file_id: str) -> bytes:
        """讀回已存的檔案內容（使用者選完待辦後重新檢查用，契約 v2.11）。"""
        ...

    async def delete(self, token: str, file_id: str) -> None:
        """永久刪除檔案（不放垃圾桶）：重新檢查沒通過、選「都不是」、沒選就離開的暫存檔。"""
        ...


CLAIM_FORM_CODE = "D10"  # 理賠申請書：整趟行程一項，放在行程資料夾
CLAIM_FORM_NAME = "理賠申請書"
PENDING_NAME = "待確認"
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
    ctx: IncidentContext,
    code: str,
    todo: TodoView,
    content_type: str,
    *,
    exclude: uuid.UUID | None = None,
) -> str:
    """規格書 R8 的檔名「事故類型_待辦名稱_序號」；序號是這項待辦已存的文件數加一。

    已存的文件包含辨識通過的與使用者確認過的；`exclude` 是正在改名的那份，不算自己。
    """
    seq = 1 + sum(
        1
        for d in ctx.documents
        if d.todo_id == todo.id
        and d.id != exclude
        and (d.recognition_status == "recognized" or d.confirmed_by_user)
    )
    ext = _EXTENSIONS.get(content_type, "")
    if code == CLAIM_FORM_CODE:
        return f"{CLAIM_FORM_NAME}_{seq}{ext}"
    kind = _clean(ctx.incident_type_name or "事故")
    title = _clean(_LEADING_VERB.sub("", todo.title), 60)
    return f"{kind}_{title}_{seq}{ext}"


_PENDING_SEQ = re.compile(rf"_{PENDING_NAME}_(\d+)(?:\.\w+)?$")


def pending_file_name(ctx: IncidentContext, content_type: str) -> str:
    """「不確定」的文件還不知道是哪一項待辦：「事故類型_待確認_序號」。

    序號是這個事件裡「檔名還叫待確認」的文件沒用到的最小正整數（#197）：
    使用者確認後檔名已改成待辦名稱的，不再占號，所以不會跳號；
    確認後改名失敗、檔名仍是「待確認_N」的，繼續占號，所以不會與新的撞名。
    """
    used = {
        int(m.group(1))
        for d in ctx.documents
        if (m := _PENDING_SEQ.search(d.file_name))
    }
    seq = next(n for n in range(1, len(used) + 2) if n not in used)
    kind = _clean(ctx.incident_type_name or "事故")
    return f"{kind}_{PENDING_NAME}_{seq}{_EXTENSIONS.get(content_type, '')}"


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
    """開發與展示用的假雲端（DOCUMENT_DEV_FAKE_STORAGE）：不連網，回傳假的檔案編號。

    `saved` 記下每次存檔的「資料夾路徑／檔名」，給測試與展示看結構，不含檔案內容。
    檔案內容只放在這個程序的記憶體（重新檢查要讀回），程序重開就沒了，不寫到任何地方。
    """

    def __init__(self) -> None:
        self._names: dict[str, str] = {}
        self._contents: dict[str, bytes] = {}
        self.saved: list[str] = []
        self.renamed: list[str] = []
        self.deleted: list[str] = []

    async def ensure_folder(self, token: str, name: str, parent_id: str | None) -> str:
        path = f"{self._names.get(parent_id or '', '')}/{name}".lstrip("/")
        folder_id = f"dev-fake-folder-{uuid.uuid5(uuid.NAMESPACE_URL, path).hex[:12]}"
        self._names[folder_id] = path
        return folder_id

    async def upload(
        self, token: str, folder_id: str, name: str, content: bytes, content_type: str
    ) -> str:
        self.saved.append(f"{self._names.get(folder_id, '')}/{name}")
        file_id = f"dev-fake-file-{uuid.uuid4().hex[:12]}"
        self._contents[file_id] = content
        return file_id

    async def rename(self, token: str, file_id: str, name: str) -> None:
        self.renamed.append(f"{file_id} → {name}")

    async def download(self, token: str, file_id: str) -> bytes:
        if file_id not in self._contents:
            raise StorageFailed("假雲端沒有這個檔案（後端重開過）")
        return self._contents[file_id]

    async def delete(self, token: str, file_id: str) -> None:
        self._contents.pop(file_id, None)
        self.deleted.append(file_id)


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

    async def rename(self, token: str, file_id: str, name: str) -> None:
        try:
            async with self._client(token) as client:
                response = await client.patch(
                    f"{self.API}/{file_id}",
                    params={"fields": "id"},
                    json={"name": name},
                )
                response.raise_for_status()
        except httpx.HTTPError as e:
            raise StorageFailed(f"雲端檔案改名失敗（{type(e).__name__}）") from e

    async def download(self, token: str, file_id: str) -> bytes:
        try:
            async with self._client(token) as client:
                response = await client.get(
                    f"{self.API}/{file_id}", params={"alt": "media"}
                )
                response.raise_for_status()
                return response.content
        except httpx.HTTPError as e:
            raise StorageFailed(f"讀回雲端檔案失敗（{type(e).__name__}）") from e

    async def delete(self, token: str, file_id: str) -> None:
        """永久刪除（drive.file 只能刪 App 自己建立的檔案）；已經不在了也算成功。"""
        try:
            async with self._client(token) as client:
                response = await client.delete(f"{self.API}/{file_id}")
                if response.status_code == 404:
                    return
                response.raise_for_status()
        except httpx.HTTPError as e:
            raise StorageFailed(f"刪除雲端檔案失敗（{type(e).__name__}）") from e
