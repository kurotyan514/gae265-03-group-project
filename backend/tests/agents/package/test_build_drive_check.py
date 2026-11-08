"""契約 v2.5：build 有 Google 授權時，確認附件還在不在 Drive（#155 驗收 7-2）。

取不到的（永久刪除或在垃圾桶）不附在信裡、列在 unavailable_attachments 給畫面提示；
那項待辦沒有其他可附的文件時，信上寫「（另行提供）」，不寫給使用者的操作說明（2026-11-08 決定）。
授權與 Google 轉接器都用假的，不連 Google。
"""

import uuid

from app.agents.package import GmailClaimPackager, GoogleApiError
from app.agents.package.google_api import DriveFile, DriveFileStatus
from app.contracts import (
    DocumentView,
    IncidentContext,
    PolicySummary,
    TodoView,
    UserContext,
)

USER = UserContext(user_id=uuid.uuid4(), email="owner@example.com")


class FakeGoogleAccess:
    def __init__(self, *granted: str) -> None:
        self.granted = set(granted)

    async def access_token(self, user: UserContext, scope: str) -> str | None:
        return f"token-{scope}" if scope in self.granted else None

    async def drive_folder_id(self, user: UserContext) -> str | None:
        return None


DRIVE = FakeGoogleAccess("drive.file", "gmail.compose")


class FakeDrive:
    """假的 Drive：記下查了哪些檔；status 沒列的檔案都還在。"""

    def __init__(self, status: dict[str, DriveFileStatus] | None = None) -> None:
        self.status = status or {}
        self.checked: list[tuple[str, str]] = []
        self.error: GoogleApiError | None = None

    async def file_status(self, token: str, file_id: str) -> DriveFileStatus:
        self.checked.append((token, file_id))
        if self.error:
            raise self.error
        return self.status.get(file_id, "ok")

    async def fetch_file(self, token: str, file_id: str) -> DriveFile:
        raise AssertionError("build 不下載檔案內容")

    async def send_message(self, token: str, message: bytes) -> str:
        raise AssertionError("build 不寄信")

    async def create_draft(self, token: str, message: bytes) -> str:
        raise AssertionError("build 不建草稿")


def _todo(
    title: str,
    sort_order: int,
    *,
    scope: str = "incident",
    requires_upload: bool = True,
) -> TodoView:
    return TodoView(
        id=uuid.uuid4(),
        phase="after_return",
        title=title,
        is_done=True,
        status="done",
        done_by="agent",
        sort_order=sort_order,
        scope=scope,  # pyright: ignore[reportArgumentType]
        requires_upload=requires_upload,
    )


def _document(todo: TodoView, file_name: str, storage_path: str) -> DocumentView:
    return DocumentView(
        id=uuid.uuid4(),
        todo_id=todo.id,
        file_name=file_name,
        content_type="application/pdf",
        storage_path=storage_path,
        recognition_status="recognized",
    )


DELAY = _todo("航空業者出具、載有班機延誤期間或取消的證明", 0)
TICKET = _todo("機票及登機證，或航空業者出具的搭機證明", 1)
FORM = _todo("理賠申請書", 0, scope="policy")
DELAY_1 = _document(DELAY, "班機延誤_延誤證明_1.pdf", "drive-delay-1")
TICKET_1 = _document(TICKET, "班機延誤_機票及登機證_1.pdf", "drive-ticket-1")
TICKET_2 = _document(TICKET, "班機延誤_機票及登機證_2.pdf", "drive-ticket-2")
FORM_1 = _document(FORM, "理賠申請書_1.pdf", "drive-form-1")


def _ctx(*documents: DocumentView) -> IncidentContext:
    return IncidentContext(
        incident_id=uuid.uuid4(),
        title="班機延誤",
        description="班機延誤了六個小時",
        status="open",
        incident_type_name="班機延誤",
        policy=PolicySummary(
            plan_id="fubon_advanced",
            plan_name="富邦國外旅平險-進階型",
            insurance_codes=[],
            coverages=[],
        ),
        todos=[DELAY, TICKET, FORM],
        documents=list(documents),
    )


def _section(body: str, title: str) -> list[str] | None:
    """內文裡某一段的內容（標題下一行起到空行為止）；沒有這段回 None。"""
    lines = body.split("\n")
    if title not in lines:
        return None
    rest = lines[lines.index(title) + 1 :]
    return rest[: rest.index("")] if "" in rest else rest


async def test_附件都還在時照常附上_每個都查一次() -> None:
    drive = FakeDrive()
    ctx = _ctx(DELAY_1, TICKET_1, FORM_1)

    package = await GmailClaimPackager(google_api=drive).build(ctx, DRIVE, USER)

    assert [a.document_id for a in package.attachments] == [
        DELAY_1.id,
        TICKET_1.id,
        FORM_1.id,
    ]
    assert package.unavailable_attachments == []
    assert drive.checked == [
        ("token-drive.file", "drive-delay-1"),
        ("token-drive.file", "drive-ticket-1"),
        ("token-drive.file", "drive-form-1"),
    ]
    assert _section(package.body, "未隨信附上的文件") is None


async def test_需上傳的文件取不到又沒有其他文件時_列為還缺的待辦_不能寄出() -> None:
    # 一定要上傳的文件不能不處理（2026-11-08 決定）：列進 missing_todo_ids，平台就不讓寄出
    drive = FakeDrive({"drive-ticket-1": "trashed"})
    ctx = _ctx(DELAY_1, TICKET_1, FORM_1)

    package = await GmailClaimPackager(google_api=drive).build(ctx, DRIVE, USER)

    assert package.missing_todo_ids == [TICKET.id]
    assert [a.document_id for a in package.attachments] == [DELAY_1.id, FORM_1.id]
    assert _section(package.body, "附件清單") == [
        f"・{DELAY_1.file_name}",
        f"・{FORM_1.file_name}",
    ]
    # 不能寄出，所以不寫「另行提供」；信裡也不放給使用者的操作說明
    assert _section(package.body, "未隨信附上的文件") is None
    assert "垃圾桶" not in package.body and "重新上傳" not in package.body
    [unavailable] = package.unavailable_attachments
    assert unavailable.document_id == TICKET_1.id
    assert unavailable.file_name == TICKET_1.file_name
    assert unavailable.reason == "trashed"


async def test_不需上傳的待辦文件取不到時_信上寫另行提供_可以寄出() -> None:
    other = _todo("其他證明", 2, requires_upload=False)
    other_1 = _document(other, "班機延誤_其他證明_1.pdf", "drive-other-1")
    drive = FakeDrive({"drive-other-1": "not_found"})
    ctx = _ctx(DELAY_1, TICKET_1, FORM_1, other_1)
    ctx.todos.append(other)

    package = await GmailClaimPackager(google_api=drive).build(ctx, DRIVE, USER)

    assert package.missing_todo_ids == []
    assert _section(package.body, "未隨信附上的文件") == [
        f"・{other.title}（另行提供）"
    ]
    assert "重新上傳" not in package.body
    [unavailable] = package.unavailable_attachments
    assert (unavailable.document_id, unavailable.reason) == (other_1.id, "not_found")


async def test_同一項待辦已重新上傳時_舊檔不附_也不再提示() -> None:
    # 使用者照提示重新上傳：新的那份照常附上；舊檔已經不需要，提示框不再列（2026-11-08 決定）
    for reason in ("not_found", "trashed"):
        drive = FakeDrive({"drive-ticket-1": reason})
        ctx = _ctx(DELAY_1, TICKET_1, TICKET_2, FORM_1)

        package = await GmailClaimPackager(google_api=drive).build(ctx, DRIVE, USER)

        assert [a.document_id for a in package.attachments] == [
            DELAY_1.id,
            TICKET_2.id,
            FORM_1.id,
        ], reason
        assert package.unavailable_attachments == [], reason
        assert package.missing_todo_ids == [], reason
        assert _section(package.body, "未隨信附上的文件") is None, reason


async def test_附件全部取不到時_每項需上傳的待辦都列為還缺() -> None:
    drive = FakeDrive(
        {
            "drive-delay-1": "not_found",
            "drive-ticket-1": "trashed",
            "drive-form-1": "trashed",
        }
    )
    ctx = _ctx(DELAY_1, TICKET_1, FORM_1)

    package = await GmailClaimPackager(google_api=drive).build(ctx, DRIVE, USER)

    assert package.attachments == []
    assert package.missing_todo_ids == [DELAY.id, TICKET.id, FORM.id]
    assert _section(package.body, "附件清單") == ["・（無）"]
    assert [u.reason for u in package.unavailable_attachments] == [
        "not_found",
        "trashed",
        "trashed",
    ]


async def test_沒有Drive授權時不檢查_照舊全部附上() -> None:
    drive = FakeDrive({"drive-ticket-1": "trashed"})
    ctx = _ctx(DELAY_1, TICKET_1, FORM_1)

    package = await GmailClaimPackager(google_api=drive).build(
        ctx, FakeGoogleAccess("gmail.compose"), USER
    )

    assert len(package.attachments) == 3
    assert package.unavailable_attachments == []
    assert drive.checked == []


async def test_查不到時不能少附_照舊全部附上() -> None:
    # 授權失效或暫時連不上：不確定檔案在不在，不能因此少附；寄出時 send 會再檢查一次
    for kind in ("unauthorized", "unavailable"):
        drive = FakeDrive()
        drive.error = GoogleApiError(kind)
        ctx = _ctx(DELAY_1, TICKET_1, FORM_1)

        package = await GmailClaimPackager(google_api=drive).build(ctx, DRIVE, USER)

        assert len(package.attachments) == 3, kind
        assert package.unavailable_attachments == [], kind
        assert _section(package.body, "未隨信附上的文件") is None, kind


async def test_只給ctx時不檢查() -> None:
    # 舊的呼叫方式與 /dev/package 的範例：不連 Drive
    drive = FakeDrive({"drive-ticket-1": "trashed"})
    ctx = _ctx(DELAY_1, TICKET_1, FORM_1)

    package = await GmailClaimPackager(google_api=drive).build(ctx)

    assert len(package.attachments) == 3
    assert drive.checked == []


async def test_沒有Google轉接器時不檢查() -> None:
    ctx = _ctx(DELAY_1, TICKET_1, FORM_1)

    package = await GmailClaimPackager().build(ctx, DRIVE, USER)

    assert len(package.attachments) == 3
    assert package.unavailable_attachments == []
