"""6 號文件辨識：只看契約輸出（Recognition），Azure、Drive、LLM 都是假的。"""

import logging
import uuid

import pytest
from app.agents.document.reader import Line
from app.agents.document.recognizer import (
    AMBIGUOUS_KIND,
    BLURRY,
    MANY_TODOS,
    NEED_GOOGLE,
    NEED_OCR,
    NO_TODO,
    SAVE_FAILED,
    UNKNOWN_KIND,
)
from app.agents.document.storage import DRIVE_SCOPE, ROOT_FOLDER_NAME
from app.contracts import DocumentView

from tests.agents.document_helpers import (
    D01_TODO,
    D02_TODO,
    DELAY_TEXT,
    JPEG,
    USER,
    FakeDrive,
    FakeGoogle,
    FakeGoogleWithFolder,
    FakeOcr,
    agent,
    context,
    pdf,
    todo,
    upload,
    verified_rules,
)


async def test_delay_certificate_is_recognized_saved_and_ticks_its_todo() -> None:
    drive = FakeDrive()
    google = FakeGoogle()
    ctx = context()
    result = await agent(drive=drive).recognize(
        ctx, upload(pdf(DELAY_TEXT), "王小明_延誤證明.pdf"), USER, google
    )
    assert result.status == "recognized"
    assert result.document_kind == "D01 延誤／取消證明"
    assert result.matched_todo_id == ctx.todos[0].id
    assert result.todo_complete
    assert result.storage_path in drive.files
    assert google.scopes == [DRIVE_SCOPE]
    folder_id, name, _ = drive.files[result.storage_path]
    assert "王小明" not in name and name.startswith("D01-")
    # 理賠資料夾底下每個事件一個子資料夾
    root = drive.folders[(ROOT_FOLDER_NAME, None)]
    assert drive.folders[(str(ctx.incident_id), root)] == folder_id


async def test_platform_provided_claim_folder_is_used() -> None:
    drive = FakeDrive()
    ctx = context()
    await agent(drive=drive).recognize(
        ctx,
        upload(pdf(DELAY_TEXT)),
        USER,
        FakeGoogleWithFolder(folder_id="platform-folder"),
    )
    assert (str(ctx.incident_id), "platform-folder") in drive.folders
    assert (ROOT_FOLDER_NAME, None) not in drive.folders


async def test_claim_form_matches_the_trip_todo() -> None:
    ctx = context()
    result = await agent().recognize(
        ctx, upload(pdf("旅行平安保險理賠申請書\n被保險人：王小明")), USER, FakeGoogle()
    )
    assert result.status == "recognized"
    assert result.document_kind == "D10 理賠申請書"
    assert result.matched_todo_id == ctx.todos[2].id
    assert result.todo_complete


async def test_boarding_pass_alone_is_saved_but_does_not_finish_the_todo() -> None:
    ctx = context()
    result = await agent().recognize(
        ctx, upload(pdf("BOARDING PASS\nBR198 TPE-NRT")), USER, FakeGoogle()
    )
    assert result.status == "recognized"
    assert result.document_kind == "D02 登機證"
    assert result.matched_todo_id == ctx.todos[1].id
    assert not result.todo_complete
    assert result.reason and "機票" in result.reason


async def test_ticket_plus_earlier_boarding_pass_finishes_the_todo() -> None:
    d02 = todo(D02_TODO)
    earlier = DocumentView(
        id=uuid.uuid4(),
        todo_id=d02.id,
        file_name="upload",
        content_type="application/pdf",
        storage_path="drive-file-x",
        recognition_status="recognized",
        document_kind="D02 登機證",
    )
    ctx = context([todo(D01_TODO), d02], [earlier])
    result = await agent().recognize(
        ctx, upload(pdf("電子機票 E-TICKET\nTicket Number 695")), USER, FakeGoogle()
    )
    assert result.document_kind == "D02 機票"
    assert result.matched_todo_id == d02.id
    assert result.todo_complete and result.reason is None


async def test_one_boarding_certificate_finishes_the_todo() -> None:
    result = await agent().recognize(
        context(), upload(pdf("搭機證明 Certificate of Boarding")), USER, FakeGoogle()
    )
    assert result.document_kind == "D02 搭機證明"
    assert result.todo_complete


async def test_without_google_grant_nothing_is_saved_or_ticked() -> None:
    drive = FakeDrive()
    result = await agent(drive=drive).recognize(
        context(), upload(pdf(DELAY_TEXT)), USER, FakeGoogle(token=None)
    )
    assert result.status == "needs_review"
    assert result.reason == NEED_GOOGLE
    assert not result.todo_complete and result.storage_path is None
    assert not drive.files


async def test_storage_failure_is_never_recognized() -> None:
    result = await agent(drive=FakeDrive(fail=True)).recognize(
        context(), upload(pdf(DELAY_TEXT)), USER, FakeGoogle()
    )
    assert result.status == "needs_review"
    assert result.reason == SAVE_FAILED
    assert result.storage_path is None and not result.todo_complete


async def test_two_matching_todos_need_the_user_to_choose() -> None:
    ctx = context([todo(D01_TODO), todo("取得航班延誤證明（回程）")])
    result = await agent().recognize(ctx, upload(pdf(DELAY_TEXT)), USER, FakeGoogle())
    assert result.status == "needs_review"
    assert result.reason == MANY_TODOS
    assert result.matched_todo_id is None


async def test_no_matching_todo_needs_the_user_to_choose() -> None:
    ctx = context([todo(D02_TODO)])
    result = await agent().recognize(ctx, upload(pdf(DELAY_TEXT)), USER, FakeGoogle())
    assert result.status == "needs_review"
    assert result.reason == NO_TODO


async def test_not_applicable_todo_is_not_matched() -> None:
    ctx = context([todo(D01_TODO, status="not_applicable")])
    result = await agent().recognize(ctx, upload(pdf(DELAY_TEXT)), USER, FakeGoogle())
    assert result.reason == NO_TODO


async def test_unknown_document_needs_review() -> None:
    result = await agent().recognize(
        context(), upload(pdf("隨便一張收據 合計 500")), USER, FakeGoogle()
    )
    assert result.status == "needs_review"
    assert result.reason == UNKNOWN_KIND


async def test_ambiguous_document_needs_review() -> None:
    result = await agent().recognize(
        context(), upload(pdf("延誤證明\n登機證")), USER, FakeGoogle()
    )
    assert result.status == "needs_review"
    assert result.reason == AMBIGUOUS_KIND


async def test_llm_fallback_is_always_needs_review_and_sees_no_personal_data() -> None:
    seen: list[str] = []

    async def guess(text: str) -> str | None:
        seen.append(text)
        return "D01"

    result = await agent(classify_fallback=guess).recognize(
        context(),
        upload(pdf("被保險人：王\n小明\n手機 0912-345-678\n航班 BR198"), "王小明.pdf"),
        USER,
        FakeGoogle(),
    )
    assert result.status == "needs_review"
    assert result.document_kind == "D01 延誤／取消證明"
    assert not result.todo_complete and result.matched_todo_id is None
    assert seen and "小明" not in seen[0] and "0912" not in seen[0]


async def test_photo_without_ocr_configured_needs_review() -> None:
    result = await agent(ocr=None).recognize(
        context(), upload(JPEG, "photo.jpg", "image/jpeg"), USER, FakeGoogle()
    )
    assert result.status == "needs_review"
    assert result.reason == NEED_OCR


async def test_photo_is_read_by_ocr() -> None:
    ocr = FakeOcr([Line(t, 0.95) for t in DELAY_TEXT.splitlines()])
    result = await agent(ocr=ocr).recognize(
        context(), upload(JPEG, "photo.jpg", "image/jpeg"), USER, FakeGoogle()
    )
    assert ocr.calls == 1
    assert result.status == "recognized"


async def test_text_pdf_is_not_sent_to_ocr() -> None:
    ocr = FakeOcr([])
    await agent(ocr=ocr).recognize(
        context(), upload(pdf(DELAY_TEXT)), USER, FakeGoogle()
    )
    assert ocr.calls == 0


async def test_blurry_photo_fails() -> None:
    ocr = FakeOcr([Line(t, 0.4) for t in DELAY_TEXT.splitlines()])
    result = await agent(ocr=ocr).recognize(
        context(), upload(JPEG, "photo.jpg", "image/jpeg"), USER, FakeGoogle()
    )
    assert result.status == "failed"
    assert result.reason == BLURRY


async def test_unsupported_or_broken_file_fails() -> None:
    word = await agent().recognize(
        context(),
        upload(b"PK\x03\x04", "a.docx", "application/zip"),
        USER,
        FakeGoogle(),
    )
    broken = await agent().recognize(
        context(), upload(b"%PDF-1.4 broken"), USER, FakeGoogle()
    )
    assert word.status == "failed" and broken.status == "failed"


# 合格規範（規則經使用者確認後才生效）


async def test_unverified_rules_are_not_applied() -> None:
    result = await agent().recognize(
        context(), upload(pdf("班機延誤證明\n航班 BR198")), USER, FakeGoogle()
    )
    assert result.status == "recognized"


async def test_verified_rule_missing_field_fails() -> None:
    result = await agent(rules=verified_rules()).recognize(
        context(), upload(pdf("班機延誤證明\n航班 BR198")), USER, FakeGoogle()
    )
    assert result.status == "failed"
    assert result.reason and "起飛時間" in result.reason


async def test_verified_rules_pass_a_qualified_document() -> None:
    result = await agent(rules=verified_rules()).recognize(
        context(), upload(pdf(DELAY_TEXT)), USER, FakeGoogle()
    )
    assert result.status == "recognized"


async def test_low_confidence_field_fails() -> None:
    lines = [Line(t, 0.95) for t in DELAY_TEXT.splitlines()]
    lines[2] = Line(lines[2].text, 0.6)
    result = await agent(ocr=FakeOcr(lines), rules=verified_rules()).recognize(
        context(), upload(JPEG, "photo.jpg", "image/jpeg"), USER, FakeGoogle()
    )
    assert result.status == "failed"
    assert result.reason and "看不清楚" in result.reason


async def test_handwritten_field_needs_review() -> None:
    lines = [Line(t, 0.95) for t in DELAY_TEXT.splitlines()]
    lines[4] = Line(lines[4].text, 0.95, handwritten=True)
    result = await agent(ocr=FakeOcr(lines), rules=verified_rules()).recognize(
        context(), upload(JPEG, "photo.jpg", "image/jpeg"), USER, FakeGoogle()
    )
    assert result.status == "needs_review"
    assert result.reason and "手寫" in result.reason
    assert not result.todo_complete


# 個資：reason 與 log 不含文件內容


PERSONAL = ["王小明", "A123456789", "0912-345-678", "BR198", "10:30"]


@pytest.mark.parametrize(
    "google, drive",
    [
        (FakeGoogle(), FakeDrive()),
        (FakeGoogle(token=None), FakeDrive()),
        (FakeGoogle(), FakeDrive(fail=True)),
    ],
)
async def test_reason_and_log_contain_no_document_content(
    caplog: pytest.LogCaptureFixture, google: FakeGoogle, drive: FakeDrive
) -> None:
    caplog.set_level(logging.DEBUG)
    text = DELAY_TEXT + "\n被保險人：王小明\n身分證字號：A123456789\n手機 0912-345-678"
    result = await agent(drive=drive, rules=verified_rules()).recognize(
        context(), upload(pdf(text), "王小明_延誤證明.pdf"), USER, google
    )
    for secret in PERSONAL:
        assert secret not in (result.reason or "")
        assert secret not in caplog.text
    assert "王小明" not in (result.document_kind or "")
