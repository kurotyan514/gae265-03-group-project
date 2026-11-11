"""7 號 agent 的 send：從 Drive 取附件、用 Gmail 寄出（規格：docs/specs/agent-7-package.md「寄送」）。

授權與 Google 轉接器都用假的，不連 Google。
"""

import uuid
from email import message_from_bytes, policy
from email.message import EmailMessage

from app.agents.package import DriveFile, GmailClaimPackager, GoogleApiError
from app.agents.package.google_api import DriveFileStatus
from app.contracts import (
    AttachmentRef,
    ClaimPackage,
    IncidentContext,
    PolicySummary,
    UserContext,
)

USER = UserContext(user_id=uuid.uuid4(), email="owner@example.com")


class FakeGoogleAccess:
    """只回給定權限的 token；其他權限回 None。"""

    def __init__(self, *granted: str) -> None:
        self.granted = set(granted)

    async def access_token(self, user: UserContext, scope: str) -> str | None:
        return f"token-{scope}" if scope in self.granted else None

    async def drive_folder_id(self, user: UserContext) -> str | None:
        return "folder-id" if "drive.file" in self.granted else None


def _ctx() -> IncidentContext:
    return IncidentContext(
        incident_id=uuid.uuid4(),
        title="班機延誤",
        description="班機延誤了六個小時",
        status="open",
        policy=PolicySummary(
            plan_id="fubon_advanced",
            plan_name="富邦國外旅平險-進階型",
            insurance_codes=[],
            coverages=[],
        ),
    )


BOTH = ("gmail.compose", "drive.file")


class FakeGoogleApi:
    """假的 Google 轉接器：Drive 上有哪些檔、寄出了哪些信，都記在記憶體裡。"""

    def __init__(self, files: dict[str, DriveFile] | None = None) -> None:
        self.files = files or {}
        self.trashed: set[str] = set()
        self.fetched: list[tuple[str, str]] = []
        self.sent: list[tuple[str, EmailMessage]] = []
        self.drafts: list[tuple[str, EmailMessage]] = []
        self.fetch_error: GoogleApiError | None = None
        self.send_error: GoogleApiError | None = None
        self.draft_error: GoogleApiError | None = None

    async def file_status(self, token: str, file_id: str) -> DriveFileStatus:
        # send 不用它（build 預覽時才查）；轉接器介面要有
        if file_id in self.trashed:
            return "trashed"
        return "ok" if file_id in self.files else "not_found"

    async def fetch_file(self, token: str, file_id: str) -> DriveFile:
        self.fetched.append((token, file_id))
        if self.fetch_error:
            raise self.fetch_error
        if file_id in self.trashed:
            raise GoogleApiError("trashed")
        if file_id not in self.files:
            raise GoogleApiError("not_found")
        return self.files[file_id]

    async def send_message(self, token: str, message: bytes) -> str:
        if self.send_error:
            raise self.send_error
        parsed = message_from_bytes(message, policy=policy.default)
        assert isinstance(parsed, EmailMessage)
        self.sent.append((token, parsed))
        return f"message-{len(self.sent)}"

    async def create_draft(self, token: str, message: bytes) -> str:
        if self.draft_error:
            raise self.draft_error
        parsed = message_from_bytes(message, policy=policy.default)
        assert isinstance(parsed, EmailMessage)
        self.drafts.append((token, parsed))
        return f"draft-{len(self.drafts)}"


DELAY = DriveFile(
    name="班機延誤_航空業者出具的延誤證明_1.pdf",
    mime_type="application/pdf",
    content=b"%PDF delay",
)
FORM = DriveFile(name="理賠申請書_1.jpg", mime_type="image/jpeg", content=b"jpeg form")


def _attachment(storage_path: str, file_name: str) -> AttachmentRef:
    return AttachmentRef(
        document_id=uuid.uuid4(), file_name=file_name, storage_path=storage_path
    )


def _filled_package(*attachments: AttachmentRef) -> ClaimPackage:
    """使用者在預覽頁填完所有空格的信。"""
    return ClaimPackage(
        subject="旅遊保險理賠申請－富邦國外旅平險-進階型－2026/08/10～08/14",
        body="您好：\n我是被保險人王小明，…\n聯絡電話：0912345678",
        attachments=list(attachments),
    )


async def _send_with(
    mail: FakeGoogleApi,
    package: ClaimPackage,
    google: FakeGoogleAccess | None = None,
):
    return await GmailClaimPackager(google_api=mail).send(
        _ctx(), package, "claims@example.com", USER, google or FakeGoogleAccess(*BOTH)
    )


async def test_信裡還有空格時回failed並列出要填的項目_不取檔也不寄出() -> None:
    # 有空格的信不能寄出（規格「寄送」）；前端與平台都會先擋，這是最後一道防線
    mail = FakeGoogleApi({"drive-1": DELAY})
    package = ClaimPackage(
        subject="旅遊保險理賠申請－富邦國外旅平險-進階型－（請填寫保險期間）",
        body="我是被保險人（請填寫被保險人姓名）…\n聯絡電話：（請填寫聯絡電話）\n（請填寫保險期間）",
        attachments=[_attachment("drive-1", DELAY.name)],
    )

    result = await _send_with(mail, package)

    assert result.status == "failed"
    assert result.external_ref is None
    assert (
        result.reason
        == "信裡還有要填寫的項目：保險期間、被保險人姓名、聯絡電話，填完才能寄出"
    )
    assert mail.fetched == []
    assert mail.sent == []


async def test_寄出成功回sent與信件編號() -> None:
    mail = FakeGoogleApi({"drive-1": DELAY})

    result = await _send_with(mail, _filled_package(_attachment("drive-1", DELAY.name)))

    assert result.status == "sent"
    assert result.external_ref == "message-1"
    assert result.reason is None
    assert len(mail.sent) == 1


async def test_用Drive的授權取每個附件_用Gmail的授權寄出() -> None:
    mail = FakeGoogleApi({"drive-1": DELAY, "drive-2": FORM})
    package = _filled_package(
        _attachment("drive-1", DELAY.name), _attachment("drive-2", FORM.name)
    )

    await _send_with(mail, package)

    assert mail.fetched == [
        ("token-drive.file", "drive-1"),
        ("token-drive.file", "drive-2"),
    ]
    assert [token for token, _ in mail.sent] == ["token-gmail.compose"]


async def test_寄出的信_寄件者收件人主旨內文() -> None:
    mail = FakeGoogleApi()
    package = _filled_package()

    await _send_with(mail, package)

    _, message = mail.sent[0]
    assert message["From"] == "owner@example.com"
    assert message["To"] == "claims@example.com"
    assert message["Subject"] == package.subject
    body = message.get_body(preferencelist=("plain",))
    assert body is not None
    # 寄出的信照郵件標準用 CRLF 換行
    assert body.get_content().replace("\r\n", "\n").rstrip("\n") == package.body


async def test_附件照送件包的順序_檔名與內容取自Drive() -> None:
    # 實際檔名從 Drive 讀（規格「附件規則」）；送件包上的檔名只是預覽用
    mail = FakeGoogleApi({"drive-1": DELAY, "drive-2": FORM})
    package = _filled_package(
        _attachment("drive-1", "預覽用的名字.pdf"), _attachment("drive-2", FORM.name)
    )

    await _send_with(mail, package)

    _, message = mail.sent[0]
    attachments = list(message.iter_attachments())
    assert [a.get_filename() for a in attachments] == [DELAY.name, FORM.name]
    assert [a.get_content_type() for a in attachments] == [
        "application/pdf",
        "image/jpeg",
    ]
    assert [a.get_content() for a in attachments] == [DELAY.content, FORM.content]


async def test_沒有附件也能寄出() -> None:
    mail = FakeGoogleApi()

    result = await _send_with(mail, _filled_package())

    assert result.status == "sent"
    assert mail.fetched == []
    assert list(mail.sent[0][1].iter_attachments()) == []


async def test_Drive上找不到附件時回failed_什麼都不寄() -> None:
    mail = FakeGoogleApi({"drive-1": DELAY})
    package = _filled_package(
        _attachment("drive-1", DELAY.name), _attachment("drive-gone", FORM.name)
    )

    result = await _send_with(mail, package)

    assert result.status == "failed"
    # 7-2：說明是哪幾個附件，檔名是系統取的、不含個資（ADR-0021）
    assert result.reason == (
        f"Google Drive 上找不到下面 1 個附件，請重新上傳：\n・{FORM.name}"
    )
    assert mail.sent == []


async def test_Drive垃圾桶裡的附件算找不到_說明到垃圾桶還原_什麼都不寄() -> None:
    # 7-2：在 Drive 刪除檔案只是移到垃圾桶，用檔案編號還讀得到，不能照樣寄出
    mail = FakeGoogleApi({"drive-1": DELAY, "drive-2": FORM})
    mail.trashed = {"drive-1", "drive-2"}
    package = _filled_package(
        _attachment("drive-1", DELAY.name), _attachment("drive-2", FORM.name)
    )

    result = await _send_with(mail, package)

    assert result.status == "failed"
    # 一個檔案一行，看得出有幾個（7-2 第一次的回饋）
    assert result.reason == (
        "下面 2 個附件在 Google Drive 的垃圾桶裡，請到 Google Drive 的垃圾桶還原後再試一次：\n"
        f"・{DELAY.name}\n・{FORM.name}"
    )
    assert mail.sent == []


async def test_找不到與在垃圾桶的附件一起列出_每個都檢查() -> None:
    # 一次列出所有有問題的附件，使用者不用一個一個試
    mail = FakeGoogleApi({"drive-1": DELAY, "drive-3": FORM})
    mail.trashed = {"drive-3"}
    package = _filled_package(
        _attachment("drive-1", DELAY.name),
        _attachment("drive-gone", "理賠申請書_1.pdf"),
        _attachment("drive-3", FORM.name),
    )

    result = await _send_with(mail, package)

    assert result.status == "failed"
    assert result.reason == (
        "Google Drive 上找不到下面 1 個附件，請重新上傳：\n・理賠申請書_1.pdf\n"
        "下面 1 個附件在 Google Drive 的垃圾桶裡，請到 Google Drive 的垃圾桶還原後再試一次：\n"
        f"・{FORM.name}"
    )
    assert [file_id for _, file_id in mail.fetched] == [
        "drive-1",
        "drive-gone",
        "drive-3",
    ]
    assert mail.sent == []


async def test_Drive授權失效時回failed請重新授權Drive() -> None:
    mail = FakeGoogleApi({"drive-1": DELAY})
    mail.fetch_error = GoogleApiError("unauthorized")

    result = await _send_with(mail, _filled_package(_attachment("drive-1", DELAY.name)))

    assert result.status == "failed"
    assert result.reason == "Google Drive 的授權已失效，請重新授權 Google Drive"
    assert mail.sent == []


async def test_Gmail授權失效時回failed請重新授權Gmail() -> None:
    mail = FakeGoogleApi()
    mail.send_error = GoogleApiError("unauthorized")

    result = await _send_with(mail, _filled_package())

    assert result.status == "failed"
    assert result.reason == "Gmail 的授權已失效，請重新授權 Gmail"


async def test_暫時連不上Google時回failed請稍後再試_不含信件內容與個資() -> None:
    # log 與 reason 只放錯誤類別，不放信件內容、email（規格「寄送」、ADR-0009）
    mail = FakeGoogleApi()
    mail.send_error = GoogleApiError("unavailable")
    package = _filled_package()

    result = await _send_with(mail, package)

    assert result.status == "failed"
    assert result.reason == "暫時連不上 Google，沒有寄出，請稍後再試"
    for secret in (
        "王小明",
        "0912345678",
        "owner@example.com",
        "claims@example.com",
        "token",
    ):
        assert secret not in result.reason


async def test_還沒接上Google轉接器時回failed_不寄出() -> None:
    # 平台目前用 GmailClaimPackager() 建立，正式的轉接器還沒做好：維持「開發中」
    result = await GmailClaimPackager().send(
        _ctx(), _filled_package(), "claims@example.com", USER, FakeGoogleAccess(*BOTH)
    )

    assert result.status == "failed"
    assert result.reason == "寄送功能開發中，尚未寄出"


# --- 建立草稿（契約 v2.1 的 mode="draft"，#154）---

BLANK_PACKAGE = ClaimPackage(
    subject="旅遊保險理賠申請－富邦國外旅平險-進階型－2026/08/10～08/14",
    body="我是被保險人（請填寫被保險人姓名）…\n聯絡電話：（請填寫聯絡電話）\n附件清單\n・"
    + DELAY.name,
    attachments=[_attachment("drive-1", DELAY.name)],
)


async def _draft_with(
    mail: FakeGoogleApi,
    package: ClaimPackage,
    recipient: str | None = None,
    google: FakeGoogleAccess | None = None,
):
    return await GmailClaimPackager(google_api=mail).send(
        _ctx(),
        package,
        recipient,
        USER,
        google or FakeGoogleAccess(*BOTH),
        mode="draft",
    )


def _plain(message: EmailMessage) -> str:
    body = message.get_body(preferencelist=("plain",))
    assert body is not None
    return body.get_content().replace("\r\n", "\n").rstrip("\n")


async def test_建立草稿成功回drafted與草稿編號_不寄出() -> None:
    mail = FakeGoogleApi({"drive-1": DELAY})

    result = await _draft_with(
        mail, _filled_package(_attachment("drive-1", DELAY.name))
    )

    assert result.status == "drafted"
    assert result.external_ref == "draft-1"
    assert result.reason is None
    assert mail.sent == []
    token, _ = mail.drafts[0]
    assert token == "token-gmail.compose"
    assert mail.fetched == [("token-drive.file", "drive-1")]


async def test_草稿有空格也能建_純文字照原樣保留空格() -> None:
    mail = FakeGoogleApi({"drive-1": DELAY})

    result = await _draft_with(mail, BLANK_PACKAGE)

    assert result.status == "drafted"
    _, message = mail.drafts[0]
    assert _plain(message) == BLANK_PACKAGE.body


async def test_草稿的帶顏色版本把每個空格用黃底紅字標出() -> None:
    # 規格「寄送」2026-11-06 決定：草稿另外產生帶顏色的版本，讓使用者在 Gmail 一眼看到要補的地方
    mail = FakeGoogleApi({"drive-1": DELAY})

    await _draft_with(mail, BLANK_PACKAGE)

    _, message = mail.drafts[0]
    html_part = message.get_body(preferencelist=("html",))
    assert html_part is not None
    html = html_part.get_content()
    for item in ("被保險人姓名", "聯絡電話"):
        marked = (
            '<span style="background-color:#ffff00;color:#d00000;font-weight:bold">'
            f"（請填寫{item}）</span>"
        )
        assert marked in html
    assert html.count("<span ") == 2


async def test_草稿的帶顏色版本會跳脫特殊字元() -> None:
    # 使用者填的值或原話可能有 < > &，不能變成 HTML
    mail = FakeGoogleApi()
    package = ClaimPackage(
        subject="主旨", body="經過：<b>延誤</b> & 取消\n（請填寫聯絡電話）"
    )

    await _draft_with(mail, package)

    _, message = mail.drafts[0]
    html_part = message.get_body(preferencelist=("html",))
    assert html_part is not None
    html = html_part.get_content()
    assert "&lt;b&gt;延誤&lt;/b&gt; &amp; 取消" in html
    assert "<b>" not in html


async def test_草稿沒有收件者時不帶收件者() -> None:
    # 自己處理的流程沒有輸入收件者，使用者到 Gmail 再填（規格「其他說明」）
    mail = FakeGoogleApi()

    result = await _draft_with(mail, _filled_package(), recipient=None)

    assert result.status == "drafted"
    _, message = mail.drafts[0]
    assert message["To"] is None
    assert message["From"] == USER.email


async def test_草稿有收件者時帶上收件者() -> None:
    mail = FakeGoogleApi()

    await _draft_with(mail, _filled_package(), recipient="claims@example.com")

    _, message = mail.drafts[0]
    assert message["To"] == "claims@example.com"


async def test_草稿與寄出用同一份信件內容與附件() -> None:
    files = {"drive-1": DELAY, "drive-2": FORM}
    package = _filled_package(
        _attachment("drive-1", DELAY.name), _attachment("drive-2", FORM.name)
    )
    sent_mail = FakeGoogleApi(files)
    draft_mail = FakeGoogleApi(files)

    await _send_with(sent_mail, package)
    await _draft_with(draft_mail, package, recipient="claims@example.com")

    _, sent = sent_mail.sent[0]
    _, draft = draft_mail.drafts[0]
    for header in ("From", "To", "Subject"):
        assert sent[header] == draft[header]
    assert _plain(sent) == _plain(draft) == package.body

    def files_of(message: EmailMessage) -> list[tuple[str | None, bytes]]:
        return [(a.get_filename(), a.get_content()) for a in message.iter_attachments()]

    assert (
        files_of(sent)
        == files_of(draft)
        == [
            (DELAY.name, DELAY.content),
            (FORM.name, FORM.content),
        ]
    )


async def test_附件檔名重複時加序號_寄出與草稿都一樣() -> None:
    # #74：一項待辦可收多份文件，附件檔名不能重名
    same = DriveFile(name="理賠申請書_1.pdf", mime_type="application/pdf", content=b"a")
    files = {"drive-1": same, "drive-2": same, "drive-3": same}
    package = _filled_package(
        *(_attachment(f"drive-{i}", same.name) for i in (1, 2, 3))
    )
    sent_mail = FakeGoogleApi(files)
    draft_mail = FakeGoogleApi(files)

    await _send_with(sent_mail, package)
    await _draft_with(draft_mail, package)

    for message in (sent_mail.sent[0][1], draft_mail.drafts[0][1]):
        assert [a.get_filename() for a in message.iter_attachments()] == [
            "理賠申請書_1.pdf",
            "理賠申請書_1_2.pdf",
            "理賠申請書_1_3.pdf",
        ]


async def test_建立草稿時Drive上找不到附件回failed_不建草稿() -> None:
    mail = FakeGoogleApi()

    result = await _draft_with(mail, BLANK_PACKAGE)

    assert result.status == "failed"
    assert result.reason == (
        f"Google Drive 上找不到下面 1 個附件，請重新上傳：\n・{DELAY.name}"
    )
    assert mail.drafts == []


async def test_建立草稿時附件在垃圾桶回failed_不建草稿() -> None:
    mail = FakeGoogleApi({"drive-1": DELAY})
    mail.trashed = {"drive-1"}

    result = await _draft_with(mail, BLANK_PACKAGE)

    assert result.status == "failed"
    assert result.reason and "垃圾桶" in result.reason and DELAY.name in result.reason
    assert mail.drafts == []


async def test_建立草稿時Gmail授權失效回failed請重新授權Gmail() -> None:
    mail = FakeGoogleApi()
    mail.draft_error = GoogleApiError("unauthorized")

    result = await _draft_with(mail, _filled_package())

    assert result.status == "failed"
    assert result.reason == "Gmail 的授權已失效，請重新授權 Gmail"


async def test_建立草稿時暫時連不上Google回failed_說明沒有建立草稿() -> None:
    mail = FakeGoogleApi({"drive-1": DELAY})
    mail.draft_error = GoogleApiError("unavailable")

    result = await _draft_with(mail, BLANK_PACKAGE, recipient="claims@example.com")

    assert result.status == "failed"
    assert result.reason == "暫時連不上 Google，沒有建立草稿，請稍後再試"
    for secret in ("owner@example.com", "claims@example.com", "token"):
        assert secret not in result.reason


async def test_建立草稿時取檔暫時連不上_說明沒有建立草稿() -> None:
    mail = FakeGoogleApi({"drive-1": DELAY})
    mail.fetch_error = GoogleApiError("unavailable")

    result = await _draft_with(mail, BLANK_PACKAGE)

    assert result.status == "failed"
    assert result.reason == "暫時連不上 Google，沒有建立草稿，請稍後再試"
    assert mail.drafts == []


async def test_還沒接上Google轉接器時建立草稿回failed() -> None:
    result = await GmailClaimPackager().send(
        _ctx(), BLANK_PACKAGE, None, USER, FakeGoogleAccess(*BOTH), mode="draft"
    )

    assert result.status == "failed"
    assert result.reason == "建立草稿功能開發中，尚未建立"
