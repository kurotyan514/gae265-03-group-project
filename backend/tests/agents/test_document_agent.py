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
    NOT_A_CLAIM_DOCUMENT,
    NOT_IN_TODOS,
    SAVE_FAILED,
    UNKNOWN_KIND,
    WRONG_TODO,
)
from app.agents.document.rules import load_rules
from app.agents.document.storage import DRIVE_SCOPE, ROOT_FOLDER_NAME
from app.agents.document.walkthrough import sample_file
from app.contracts import DocumentView, Recognition

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
    unverified_rules,
    upload,
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
    # 檔名照規格書 R8「事故類型_待辦名稱_序號」，不用使用者的原檔名
    assert name == "班機延誤_航空公司開立班機延誤／取消證明_1.pdf"
    # 平台資料庫用同一個檔名（契約 v2 的 stored_name）
    assert result.stored_name == name
    # 理賠資料夾 → 行程 → 事故
    root = drive.folders[(ROOT_FOLDER_NAME, None)]
    trip = drive.folders[("日本 2026-11-01～11-10", root)]
    assert drive.folders[("班機延誤 2026-11-08", trip)] == folder_id


async def test_baggage_delay_sample_never_ticks_a_flight_delay_todo() -> None:
    content, content_type = sample_file("baggage_delay")
    drive = FakeDrive()
    result = await agent(drive=drive).recognize(
        context(), upload(content, content_type=content_type), USER, FakeGoogle()
    )
    # 規格 v3.7：不在這個行程的待辦裡 →「辨識失敗」，檔案不留
    assert result.status == "failed" and result.failure == "not_matched"
    assert result.storage_path is None and not drive.files
    assert result.document_kind is None
    assert result.matched_todo_id is None
    assert not result.todo_complete


@pytest.mark.parametrize(
    "title",
    [
        "行李延誤證明書",
        "行李延遲證明",
        "BAGGAGE DELAY CERTIFICATE",
        "Delayed Baggage — Delay Confirmation",
        "手荷物遅延証明書",
    ],
)
async def test_baggage_delay_text_never_ticks_a_flight_delay_todo(title: str) -> None:
    result = await agent(
        ocr=FakeOcr([Line(title + "\n延誤時間：6 小時", 0.99)])
    ).recognize(context(), upload(JPEG, content_type="image/jpeg"), USER, FakeGoogle())
    assert result.status == "failed" and result.failure == "not_matched"
    assert result.document_kind is None
    assert result.matched_todo_id is None
    assert not result.todo_complete


async def test_flight_delay_with_baggage_information_still_ticks_its_todo() -> None:
    ctx = context()
    result = await agent().recognize(
        ctx,
        upload(pdf(DELAY_TEXT + "\n行李額度 Baggage allowance：23KG")),
        USER,
        FakeGoogle(),
    )
    assert result.status == "recognized"
    assert result.matched_todo_id == ctx.todos[0].id
    assert result.todo_complete


async def test_platform_provided_claim_folder_is_used() -> None:
    drive = FakeDrive()
    ctx = context()
    await agent(drive=drive).recognize(
        ctx,
        upload(pdf(DELAY_TEXT)),
        USER,
        FakeGoogleWithFolder(folder_id="platform-folder"),
    )
    assert ("日本 2026-11-01～11-10", "platform-folder") in drive.folders
    assert (ROOT_FOLDER_NAME, None) not in drive.folders


async def test_claim_form_is_stored_in_the_trip_folder() -> None:
    drive = FakeDrive()
    result = await agent(drive=drive).recognize(
        context(), upload(pdf("旅行平安保險理賠申請書")), USER, FakeGoogle()
    )
    folder_id, name, _ = drive.files[result.storage_path or ""]
    root = drive.folders[(ROOT_FOLDER_NAME, None)]
    assert folder_id == drive.folders[("日本 2026-11-01～11-10", root)]
    assert name == "理賠申請書_1.pdf"
    assert result.stored_name == name


async def test_second_file_of_the_same_todo_gets_the_next_number() -> None:
    d02 = todo("機票及登機證，或航空業者出具的搭機證明")
    earlier = DocumentView(
        id=uuid.uuid4(),
        todo_id=d02.id,
        file_name="upload",
        content_type="application/pdf",
        storage_path="drive-file-x",
        recognition_status="recognized",
        document_kind="D02 登機證",
    )
    drive = FakeDrive()
    result = await agent(drive=drive).recognize(
        context([todo(D01_TODO), d02], [earlier]),
        upload(pdf("電子機票 E-TICKET")),
        USER,
        FakeGoogle(),
    )
    _, name, _ = drive.files[result.storage_path or ""]
    assert name == "班機延誤_機票及登機證，或航空業者出具的搭機證明_2.pdf"


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


async def test_combined_ticket_boarding_sample_finishes_the_todo() -> None:
    content, content_type = sample_file("ticket_boarding")
    ctx = context()
    drive = FakeDrive()
    result = await agent(drive=drive).recognize(
        ctx, upload(content, content_type=content_type), USER, FakeGoogle()
    )
    assert result.status == "recognized"
    assert result.document_kind == "D02 機票及登機證"
    assert result.matched_todo_id == ctx.todos[1].id
    assert result.todo_complete and result.reason is None
    assert result.storage_path in drive.files


@pytest.mark.parametrize(
    "text",
    [
        "機票暨登機證",
        "E-TICKET & BOARDING PASS",
        "電子機票 E-TICKET\nTicket Number 695\nBOARDING PASS",
    ],
)
async def test_combined_ticket_boarding_titles_finish_the_todo(text: str) -> None:
    ctx = context()
    result = await agent().recognize(ctx, upload(pdf(text)), USER, FakeGoogle())
    assert result.status == "recognized"
    assert result.document_kind == "D02 機票及登機證"
    assert result.matched_todo_id == ctx.todos[1].id
    assert result.todo_complete


@pytest.mark.parametrize("label", ["Ticket Number", "E-TICKET NUMBER", "機票號碼"])
async def test_boarding_pass_with_ticket_number_still_needs_a_ticket(
    label: str,
) -> None:
    result = await agent().recognize(
        context(), upload(pdf(f"BOARDING PASS\n{label} 695")), USER, FakeGoogle()
    )
    assert result.document_kind == "D02 登機證"
    assert not result.todo_complete


async def test_combined_document_with_another_document_code_needs_review() -> None:
    result = await agent().recognize(
        context(),
        upload(pdf("E-TICKET & BOARDING PASS\n理賠申請書")),
        USER,
        FakeGoogle(),
    )
    assert result.status == "needs_review"
    assert result.matched_todo_id is None
    assert not result.todo_complete


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
    # 畫面只列這兩項延誤證明待辦（規格 v3.7 第 3 點）
    assert result.candidate_todo_ids == [t.id for t in ctx.todos[:2]]


async def test_document_without_a_todo_in_this_trip_is_not_matched() -> None:
    drive = FakeDrive()
    ctx = context([todo(D02_TODO)])
    result = await agent(drive=drive).recognize(
        ctx, upload(pdf(DELAY_TEXT)), USER, FakeGoogle()
    )
    # 認得是延誤證明，但這個行程沒有它的待辦：「辨識失敗」，不留檔、不用使用者選
    assert result.status == "failed" and result.failure == "not_matched"
    assert result.reason == NOT_IN_TODOS
    assert result.document_kind == "D01 延誤／取消證明"
    assert result.matched_todo_id is None and result.storage_path is None
    assert not drive.files


async def test_not_applicable_todo_is_not_matched() -> None:
    ctx = context([todo(D01_TODO, status="not_applicable")])
    result = await agent().recognize(ctx, upload(pdf(DELAY_TEXT)), USER, FakeGoogle())
    assert result.reason == NOT_IN_TODOS


async def test_unknown_document_is_not_matched_and_not_saved() -> None:
    drive = FakeDrive()
    result = await agent(drive=drive).recognize(
        context(), upload(pdf("隨便一張收據 合計 500")), USER, FakeGoogle()
    )
    # 規格 v3.7：看不出是理賠文件 →「辨識失敗」，檔案不留
    assert result.status == "failed" and result.failure == "not_matched"
    assert result.reason == NOT_A_CLAIM_DOCUMENT
    assert result.storage_path is None and not drive.files


# 不確定的文件先存檔，使用者確認時沿用（契約 v2）


async def test_needs_review_document_is_saved_for_the_user_to_confirm() -> None:
    drive = FakeDrive()
    result = await agent(drive=drive).recognize(
        context(),
        upload(pdf("延誤證明\n登機證"), "王小明_收據.pdf"),
        USER,
        FakeGoogle(),
    )
    assert result.status == "needs_review"
    assert result.matched_todo_id is None and not result.todo_complete
    folder_id, name, _ = drive.files[result.storage_path or ""]
    # 還不知道是哪一項待辦，放在事故資料夾、檔名標「待確認」，不用原檔名
    assert name == "班機延誤_待確認_1.pdf"
    assert result.stored_name == name
    root = drive.folders[(ROOT_FOLDER_NAME, None)]
    trip = drive.folders[("日本 2026-11-01～11-10", root)]
    assert folder_id == drive.folders[("班機延誤 2026-11-08", trip)]


def _pending_doc(file_name: str, *, confirmed: bool) -> DocumentView:
    return DocumentView(
        id=uuid.uuid4(),
        todo_id=None,
        file_name=file_name,
        content_type="application/pdf",
        storage_path=f"drive-{file_name}",
        recognition_status="needs_review",
        confirmed_by_user=confirmed,
    )


async def _pending_name_with(documents: list[DocumentView]) -> str:
    """事件裡已有這些文件時，新的「不確定」文件存成什麼檔名（#197）。"""
    drive = FakeDrive()
    ctx = context().model_copy(update={"documents": documents})
    result = await agent(drive=drive).recognize(
        ctx, upload(pdf("延誤證明\n登機證")), USER, FakeGoogle()
    )
    assert result.status == "needs_review"
    return drive.files[result.storage_path or ""][1]


async def test_pending_number_skips_confirmed_and_renamed_documents() -> None:
    # 已確認並成功改名的文件，檔名已經是待辦名稱，不再占「待確認」的序號
    renamed = [
        _pending_doc("班機延誤_原定機票與登機證_1.pdf", confirmed=True),
        _pending_doc("班機延誤_延誤證明_1.pdf", confirmed=True),
    ]
    assert await _pending_name_with(renamed) == "班機延誤_待確認_1.pdf"


async def test_pending_number_does_not_collide_with_a_failed_rename() -> None:
    # 已確認但改名失敗的文件仍叫「待確認_1」：新的要換號，不與它撞名
    stuck = _pending_doc("班機延誤_待確認_1.pdf", confirmed=True)
    assert await _pending_name_with([stuck]) == "班機延誤_待確認_2.pdf"


async def test_pending_number_counts_unconfirmed_documents() -> None:
    waiting = [_pending_doc("班機延誤_待確認_1.pdf", confirmed=False)]
    assert await _pending_name_with(waiting) == "班機延誤_待確認_2.pdf"


async def test_pending_number_takes_the_smallest_free_one() -> None:
    # 第 2 份已經確認並改名了：下一份補回空出來的 2，不是 4
    docs = [
        _pending_doc("班機延誤_待確認_1.pdf", confirmed=False),
        _pending_doc("班機延誤_延誤證明_1.pdf", confirmed=True),
        _pending_doc("班機延誤_待確認_3.pdf", confirmed=False),
    ]
    assert await _pending_name_with(docs) == "班機延誤_待確認_2.pdf"


async def test_needs_review_without_google_grant_is_not_saved() -> None:
    drive = FakeDrive()
    result = await agent(drive=drive).recognize(
        context(), upload(pdf("延誤證明\n登機證")), USER, FakeGoogle(token=None)
    )
    assert result.status == "needs_review"
    assert result.storage_path is None and not drive.files


async def test_needs_review_storage_failure_keeps_the_reason() -> None:
    result = await agent(drive=FakeDrive(fail=True)).recognize(
        context(), upload(pdf("延誤證明\n登機證")), USER, FakeGoogle()
    )
    assert result.status == "needs_review"
    assert result.reason == AMBIGUOUS_KIND
    assert result.storage_path is None


# 使用者上傳時指定的待辦（契約 v2：matched_todo_id 只能是它或空）


async def test_chosen_todo_is_used_when_the_document_fits() -> None:
    first, second = todo(D01_TODO), todo("取得航班延誤證明（回程）")
    file = upload(pdf(DELAY_TEXT))
    file.target_todo_id = second.id
    result = await agent().recognize(context([first, second]), file, USER, FakeGoogle())
    assert result.status == "recognized"
    assert result.matched_todo_id == second.id
    assert result.todo_complete


async def test_chosen_todo_that_does_not_fit_needs_review() -> None:
    ctx = context()
    d02 = ctx.todos[1]
    file = upload(pdf(DELAY_TEXT))
    file.target_todo_id = d02.id
    drive = FakeDrive()
    result = await agent(drive=drive).recognize(ctx, file, USER, FakeGoogle())
    assert result.status == "needs_review"
    assert result.reason == WRONG_TODO
    # 不能對到別的待辦，也不能替使用者勾
    assert result.matched_todo_id is None and not result.todo_complete
    assert result.storage_path in drive.files  # 先存檔，使用者確認時沿用


async def test_chosen_todo_with_unknown_document_needs_review() -> None:
    ctx = context()
    file = upload(pdf("隨便一張收據 合計 500"))
    file.target_todo_id = ctx.todos[0].id
    result = await agent().recognize(ctx, file, USER, FakeGoogle())
    assert result.status == "needs_review"
    assert result.reason == UNKNOWN_KIND  # 使用者指定了待辦：由他確認，不判失敗
    assert result.matched_todo_id in (None, ctx.todos[0].id)
    assert not result.todo_complete


async def test_ambiguous_document_needs_review() -> None:
    ctx = context()
    result = await agent().recognize(
        ctx, upload(pdf("延誤證明\n登機證")), USER, FakeGoogle()
    )
    assert result.status == "needs_review"
    assert result.reason == AMBIGUOUS_KIND
    # 像延誤證明也像登機證：兩項待辦都是候選，其他的不列
    by_title = {t.title: t.id for t in ctx.todos}
    assert set(result.candidate_todo_ids) == {by_title[D01_TODO], by_title[D02_TODO]}


async def test_llm_fallback_is_always_needs_review_and_sees_no_personal_data() -> None:
    seen: list[str] = []

    async def guess(text: str) -> str | None:
        seen.append(text)
        return "D01"

    ctx = context()
    result = await agent(classify_fallback=guess).recognize(
        ctx,
        upload(pdf("被保險人：王\n小明\n手機 0912-345-678\n航班 BR198"), "王小明.pdf"),
        USER,
        FakeGoogle(),
    )
    assert result.status == "needs_review"
    assert result.document_kind == "D01 延誤／取消證明"
    assert not result.todo_complete and result.matched_todo_id is None
    # LLM 猜的種類只當候選，不勾、不對
    assert result.candidate_todo_ids == [t.id for t in ctx.todos if t.title == D01_TODO]
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
    assert result.status == "failed" and result.failure == "unreadable"
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
    assert word.failure == broken.failure == "unreadable"


# 合格規範（#69）：延誤期間缺了就不合格，延誤原因缺了只提醒


async def test_unverified_rules_are_not_applied() -> None:
    result = await agent(rules=unverified_rules()).recognize(
        context(), upload(pdf("班機延誤證明\n航班 BR198")), USER, FakeGoogle()
    )
    assert result.status == "recognized"


async def test_delay_without_delay_period_is_incomplete_and_not_saved() -> None:
    drive = FakeDrive()
    result = await agent(drive=drive, rules=load_rules()).recognize(
        context(),
        upload(pdf("班機延誤證明\n航班 BR198\n原因：天候")),
        USER,
        FakeGoogle(),
    )
    # 契約 v2：不合格回 incomplete，reason 寫缺什麼，不存檔、不勾待辦
    assert result.status == "incomplete"
    assert result.reason and "延誤期間" in result.reason
    assert result.failure is None
    assert result.found_fields == ["延誤原因"]
    # 規格 v3.7 第 5 點：缺少什麼＋程式套公式組出的下一步
    assert result.missing == ["延誤期間"]
    assert result.next_step == "請向航空公司索取載明延誤期間的延誤／取消證明"
    assert result.storage_path is None and not result.todo_complete
    assert not drive.files


async def test_qualified_delay_certificate_passes_without_reminder() -> None:
    result = await agent(rules=load_rules()).recognize(
        context(), upload(pdf(DELAY_TEXT)), USER, FakeGoogle()
    )
    assert result.status == "recognized" and result.todo_complete
    assert result.reason is None
    # 判斷依據只給欄位名稱，不給文件內容
    assert result.found_fields == ["延誤期間", "延誤原因"]


@pytest.mark.parametrize(
    "text",
    [
        "班機延誤證明\n航班 BR198\n延誤時間：6 小時 15 分\n原因：天候",
        "FLIGHT DELAY CERTIFICATE\nBR198\nDelayed 5 hours\nReason: weather",
        "班機取消證明\n航班 BR198 已取消\n原定起飛 10:30\n原因：颱風",
    ],
    ids=["延誤時數", "英文時數", "班機取消只有原定時間"],
)
async def test_delay_period_can_be_a_duration_or_a_cancellation(text: str) -> None:
    result = await agent(rules=load_rules()).recognize(
        context(), upload(pdf(text)), USER, FakeGoogle()
    )
    assert result.status == "recognized"


async def test_missing_delay_reason_only_reminds() -> None:
    drive = FakeDrive()
    result = await agent(drive=drive, rules=load_rules()).recognize(
        context(),
        upload(pdf("班機延誤證明\n航班 BR198\n原定起飛 10:30\n實際起飛 16:45")),
        USER,
        FakeGoogle(),
    )
    # 條款沒要求原因，照樣通過、存檔、勾待辦；但保險公司會用原因判斷不保事項，所以提醒
    assert result.status == "recognized" and result.todo_complete
    assert result.storage_path in drive.files
    assert result.reason and "原因" in result.reason
    assert result.found_fields == ["延誤期間"]


async def test_low_confidence_field_fails() -> None:
    lines = [Line(t, 0.95) for t in DELAY_TEXT.splitlines()]
    lines[2] = Line(lines[2].text, 0.6)
    result = await agent(ocr=FakeOcr(lines), rules=load_rules()).recognize(
        context(), upload(JPEG, "photo.jpg", "image/jpeg"), USER, FakeGoogle()
    )
    assert result.status == "failed"
    assert result.reason and "看不清楚" in result.reason


async def test_handwritten_field_needs_review() -> None:
    lines = [Line(t, 0.95) for t in DELAY_TEXT.splitlines()]
    lines[3] = Line(lines[3].text, 0.95, handwritten=True)
    result = await agent(ocr=FakeOcr(lines), rules=load_rules()).recognize(
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
    result = await agent(drive=drive, rules=load_rules()).recognize(
        context(), upload(pdf(text), "王小明_延誤證明.pdf"), USER, google
    )
    for secret in PERSONAL:
        assert secret not in (result.reason or "")
        assert secret not in caplog.text
    assert "王小明" not in (result.document_kind or "")


# 使用者確認「不確定」的文件後改檔名（契約 v2.2，#160）


async def _saved_pending(drive: FakeDrive):
    """6 號先把「不確定」的文件存成「班機延誤_待確認_1.pdf」，回傳（ctx、文件、待辦）。"""
    d02 = todo(D02_TODO)
    ctx = context([todo(D01_TODO), d02])
    result = await agent(drive=drive).recognize(
        ctx, upload(pdf("延誤證明\n登機證")), USER, FakeGoogle()
    )
    document = DocumentView(
        id=uuid.uuid4(),
        todo_id=d02.id,
        file_name=result.stored_name or "",
        content_type="application/pdf",
        storage_path=result.storage_path or "",
        recognition_status="needs_review",
        confirmed_by_user=True,
    )
    return ctx.model_copy(update={"documents": [document]}), document, d02


async def test_confirmed_document_is_renamed_to_its_todo_name() -> None:
    drive = FakeDrive()
    ctx, document, d02 = await _saved_pending(drive)
    assert drive.files[document.storage_path][1] == "班機延誤_待確認_1.pdf"

    name = await agent(drive=drive).rename_confirmed(
        ctx, document, d02, USER, FakeGoogle()
    )

    # Drive 上的檔案改名，回傳的名字交給平台寫進資料庫；不含原檔名
    assert name == "班機延誤_原定機票與登機證_1.pdf"
    assert drive.files[document.storage_path][1] == name


async def test_second_confirmed_document_of_a_todo_gets_the_next_number() -> None:
    drive = FakeDrive()
    ctx, document, d02 = await _saved_pending(drive)
    earlier = DocumentView(
        id=uuid.uuid4(),
        todo_id=d02.id,
        file_name="x",
        content_type="application/pdf",
        storage_path="drive-file-x",
        recognition_status="needs_review",
        confirmed_by_user=True,
    )
    ctx = ctx.model_copy(update={"documents": [earlier, document]})

    name = await agent(drive=drive).rename_confirmed(
        ctx, document, d02, USER, FakeGoogle()
    )

    assert name == "班機延誤_原定機票與登機證_2.pdf"  # 不把自己算進序號


async def test_rename_without_google_grant_keeps_the_old_name() -> None:
    drive = FakeDrive()
    ctx, document, d02 = await _saved_pending(drive)

    name = await agent(drive=drive).rename_confirmed(
        ctx, document, d02, USER, FakeGoogle(token=None)
    )

    assert name is None and not drive.renames
    assert drive.files[document.storage_path][1] == "班機延誤_待確認_1.pdf"


async def test_rename_failure_keeps_the_old_name() -> None:
    drive = FakeDrive()
    ctx, document, d02 = await _saved_pending(drive)
    drive.fail = True

    name = await agent(drive=drive).rename_confirmed(
        ctx, document, d02, USER, FakeGoogle()
    )

    assert name is None


# 使用者選了待辦後重新檢查、刪除暫存檔（契約 v2.11，規格 v3.7 第 3 點）


def _view(result: Recognition, todo_id: uuid.UUID | None = None) -> DocumentView:
    return DocumentView(
        id=uuid.uuid4(),
        todo_id=todo_id,
        file_name=result.stored_name or "",
        content_type="application/pdf",
        storage_path=result.storage_path or "",
        recognition_status="needs_review",
    )


async def test_recheck_passes_renames_and_ticks_the_chosen_todo() -> None:
    drive = FakeDrive()
    first, second = todo(D01_TODO), todo("取得航班延誤證明（回程）")
    ctx = context([first, second])
    pending = await agent(drive=drive, rules=load_rules()).recognize(
        ctx, upload(pdf(DELAY_TEXT)), USER, FakeGoogle()
    )
    assert pending.status == "needs_review" and pending.storage_path in drive.files

    result = await agent(drive=drive, rules=load_rules()).recheck(
        ctx, _view(pending), second, USER, FakeGoogle()
    )

    assert result.status == "recognized" and result.todo_complete
    assert result.matched_todo_id == second.id
    assert result.storage_path == pending.storage_path  # 沿用先存的檔案
    assert drive.files[result.storage_path or ""][1] == result.stored_name
    assert result.found_fields == ["延誤期間", "延誤原因"]


async def test_recheck_that_fails_the_rules_deletes_the_file() -> None:
    drive = FakeDrive()
    ctx = context()
    d01 = next(t for t in ctx.todos if t.title == D01_TODO)
    # 像延誤證明也像登機證，但上面沒有延誤期間
    pending = await agent(drive=drive, rules=load_rules()).recognize(
        ctx, upload(pdf("延誤證明\n登機證")), USER, FakeGoogle()
    )
    assert pending.storage_path in drive.files

    result = await agent(drive=drive, rules=load_rules()).recheck(
        ctx, _view(pending), d01, USER, FakeGoogle()
    )

    assert result.status == "incomplete"
    assert result.missing == ["延誤期間"]
    assert result.next_step == "請向航空公司索取載明延誤期間的延誤／取消證明"
    assert result.storage_path is None and not result.todo_complete
    assert pending.storage_path not in drive.files  # 沒通過的不保留


async def test_recheck_without_google_grant_asks_to_retry_and_keeps_the_file() -> None:
    drive = FakeDrive()
    ctx = context()
    d01 = next(t for t in ctx.todos if t.title == D01_TODO)
    pending = await agent(drive=drive).recognize(
        ctx, upload(pdf("延誤證明\n登機證")), USER, FakeGoogle()
    )
    result = await agent(drive=drive).recheck(
        ctx, _view(pending), d01, USER, FakeGoogle(token=None)
    )
    assert result.status == "needs_review"
    assert pending.storage_path in drive.files


async def test_discard_deletes_the_pending_file() -> None:
    drive = FakeDrive()
    ctx = context()
    pending = await agent(drive=drive).recognize(
        ctx, upload(pdf("延誤證明\n登機證")), USER, FakeGoogle()
    )
    assert await agent(drive=drive).discard(ctx, _view(pending), USER, FakeGoogle())
    assert pending.storage_path not in drive.files


async def test_discard_without_google_grant_reports_failure() -> None:
    drive = FakeDrive()
    ctx = context()
    pending = await agent(drive=drive).recognize(
        ctx, upload(pdf("延誤證明\n登機證")), USER, FakeGoogle()
    )
    assert not await agent(drive=drive).discard(
        ctx, _view(pending), USER, FakeGoogle(token=None)
    )
    assert pending.storage_path in drive.files
