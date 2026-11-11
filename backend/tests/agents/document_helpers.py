"""6 號測試共用的假物件：Azure、Drive、Google 授權都是假的，不連網。"""

import uuid
from datetime import UTC, date, datetime

import pymupdf
from app.agents.document import DocumentAgent
from app.agents.document.reader import Line, ReadResult
from app.agents.document.rules import FieldRule, load_rules
from app.agents.document.storage import StorageFailed
from app.contracts import (
    DocumentView,
    IncidentContext,
    PolicySummary,
    TodoView,
    UploadedFile,
    UserContext,
)

USER = UserContext(user_id=uuid.uuid4(), email="owner@example.com")
JPEG = b"\xff\xd8\xff\xe0fake-jpeg"


def pdf(text: str) -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((50, 72), text, fontname="china-t")
    return doc.tobytes()


def upload(
    content: bytes, name: str = "upload.pdf", content_type: str = "application/pdf"
) -> UploadedFile:
    return UploadedFile(file_name=name, content_type=content_type, content=content)


def todo(title: str, phase: str = "on_site", **kw) -> TodoView:
    return TodoView(id=uuid.uuid4(), phase=phase, title=title, **kw)  # pyright: ignore[reportArgumentType]


D01_TODO = "請航空公司開立班機延誤／取消證明"
D02_TODO = "保留原定機票與登機證"
D10_TODO = "填寫理賠申請書"


def context(
    todos: list[TodoView] | None = None, documents: list[DocumentView] | None = None
) -> IncidentContext:
    return IncidentContext(
        incident_id=uuid.uuid4(),
        title="班機延誤",
        description="",
        status="open",
        destination="日本",
        occurred_at=datetime(2026, 11, 8, 9, 30, tzinfo=UTC),
        incident_type_code="flight_delay",
        incident_type_name="班機延誤",
        policy=PolicySummary(
            plan_id="fubon_advanced",
            plan_name="進階型",
            start_date=date(2026, 11, 1),
            end_date=date(2026, 11, 10),
            insurance_codes=[],
            coverages=[],
        ),
        todos=todos
        if todos is not None
        else [todo(D01_TODO), todo(D02_TODO), todo(D10_TODO, "after_return")],
        documents=documents or [],
    )


class FakeGoogle:
    def __init__(
        self, token: str | None = "token", folder_id: str | None = None
    ) -> None:
        self.token = token
        self.folder_id = folder_id
        self.scopes: list[str] = []

    async def access_token(self, user: UserContext, scope: str) -> str | None:
        self.scopes.append(scope)
        return self.token

    async def drive_folder_id(self, user: UserContext) -> str | None:
        return self.folder_id


class FakeGoogleWithFolder(FakeGoogle):
    """平台提供了理賠資料夾編號（契約 v2 的 drive_folder_id）。"""


class FakeDrive:
    def __init__(self, fail: bool = False, fail_move: bool = False) -> None:
        self.fail = fail
        self.fail_move = fail_move  # 只有搬資料夾失敗，其他照常
        self.folders: dict[tuple[str, str | None], str] = {}
        self.files: dict[str, tuple[str, str, bytes]] = {}
        self.renames: list[tuple[str, str]] = []
        self.moves: list[tuple[str, str]] = []

    async def rename(self, token: str, file_id: str, name: str) -> None:
        if self.fail:
            raise StorageFailed("雲端檔案改名失敗（HTTPStatusError）")
        folder_id, _, content = self.files[file_id]
        self.files[file_id] = (folder_id, name, content)
        self.renames.append((file_id, name))

    async def move_to_folder(self, token: str, file_id: str, folder_id: str) -> None:
        if self.fail or self.fail_move:
            raise StorageFailed("雲端檔案搬移失敗（HTTPStatusError）")
        _, name, content = self.files[file_id]
        self.files[file_id] = (folder_id, name, content)
        self.moves.append((file_id, folder_id))

    async def ensure_folder(self, token: str, name: str, parent_id: str | None) -> str:
        return self.folders.setdefault((name, parent_id), f"folder-{len(self.folders)}")

    async def upload(
        self, token: str, folder_id: str, name: str, content: bytes, content_type: str
    ) -> str:
        if self.fail:
            raise StorageFailed("上傳雲端失敗（HTTPStatusError）")
        file_id = f"drive-file-{len(self.files)}"
        self.files[file_id] = (folder_id, name, content)
        return file_id

    async def download(self, token: str, file_id: str) -> bytes:
        if self.fail:
            raise StorageFailed("讀回雲端檔案失敗（HTTPStatusError）")
        return self.files[file_id][2]

    async def delete(self, token: str, file_id: str) -> None:
        if self.fail:
            raise StorageFailed("刪除雲端檔案失敗（HTTPStatusError）")
        self.files.pop(file_id, None)


class FakeOcr:
    def __init__(self, lines: list[Line]) -> None:
        self.result = ReadResult(lines, "ocr")
        self.calls = 0

    async def read(self, content: bytes, content_type: str) -> ReadResult:
        self.calls += 1
        return self.result


def unverified_rules() -> list[FieldRule]:
    """把現有規則當成還沒確認的草稿，測試草稿不生效。"""
    from dataclasses import replace

    return [replace(r, verified=False) for r in load_rules()]


def agent(
    *,
    ocr: FakeOcr | None = None,
    drive: FakeDrive | None = None,
    rules: list[FieldRule] | None = None,
    classify_fallback=None,
) -> DocumentAgent:
    return DocumentAgent(
        ocr=ocr,
        drive=drive or FakeDrive(),
        rules=rules if rules is not None else load_rules(),
        threshold=0.8,
        classify_fallback=classify_fallback,
    )


DELAY_TEXT = "班機延誤證明\n航班 BR198\n原定起飛 10:30\n實際起飛 16:45\n原因：天候"
