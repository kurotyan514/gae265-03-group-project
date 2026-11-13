"""6 號泰國醫療 demo（#233）：D13 診斷書、D14 醫療費用收據。

Azure、Drive 都是假的；範例文件由 samples/make_samples.py 產生（--medical）。
"""

import uuid
from datetime import UTC, date, datetime

import pymupdf
import pytest
from app.agents.document.reader import Line
from app.agents.document.walkthrough import sample_file
from app.contracts import IncidentContext, PolicySummary, TodoView

from tests.agents.document_helpers import (
    JPEG,
    USER,
    FakeDrive,
    FakeGoogle,
    FakeOcr,
    agent,
    context,
    pdf,
    upload,
)

# 標題照 incident_catalog.json；平台建待辦時會帶 document_code
MEDICAL_TODOS = {
    "D13": ("on_site", "請醫院開立診斷書"),
    "D14": ("on_site", "保留醫療費用收據正本"),
    "D24": ("after_return", "準備受益人身分證明"),
    "D10": ("after_return", "填寫理賠申請書"),
}


def medical_todos(with_code: bool = True) -> list[TodoView]:
    return [
        TodoView(
            id=uuid.uuid4(),
            phase=phase,  # pyright: ignore[reportArgumentType]
            title=title,
            document_code=code if with_code else None,
        )
        for code, (phase, title) in MEDICAL_TODOS.items()
    ]


def medical_context(todos: list[TodoView] | None = None) -> IncidentContext:
    return IncidentContext(
        incident_id=uuid.uuid4(),
        title="在曼谷急性腸胃炎看門診",
        description="",
        status="open",
        destination="泰國",
        occurred_at=datetime(2026, 7, 8, 3, 0, tzinfo=UTC),
        incident_type_code="medical",
        incident_type_name="生病或受傷就醫",
        policy=PolicySummary(
            plan_id="chubb_basic",
            plan_name="安達 基礎型",
            start_date=date(2026, 7, 5),
            end_date=date(2026, 7, 12),
            insurance_codes=[],
            coverages=[],
        ),
        todos=todos if todos is not None else medical_todos(),
        documents=[],
    )


def todo_of(ctx: IncidentContext, code: str) -> TodoView:
    return next(t for t in ctx.todos if MEDICAL_TODOS[code][1] == t.title)


def sample(name: str):
    content, content_type = sample_file(name)
    return upload(content, f"{name}.pdf", content_type)


@pytest.mark.parametrize("with_code", [True, False], ids=["文件代碼", "標題關鍵字"])
async def test_medical_certificate_ticks_the_diagnosis_todo(with_code: bool) -> None:
    drive = FakeDrive()
    ctx = medical_context(medical_todos(with_code))
    result = await agent(drive=drive).recognize(
        ctx, sample("med_certificate"), USER, FakeGoogle()
    )
    assert result.status == "recognized"
    assert result.document_kind == "D13 診斷書"
    assert result.matched_todo_id == todo_of(ctx, "D13").id
    assert result.todo_complete
    # 檔名去掉待辦開頭的「請」，跟班機延誤一樣
    assert result.stored_name == "生病或受傷就醫_醫院開立診斷書_1.pdf"
    assert result.found_fields == ["病名", "就診日期"]
    assert result.reason is None


@pytest.mark.parametrize("with_code", [True, False], ids=["文件代碼", "標題關鍵字"])
async def test_medical_receipt_ticks_the_receipt_todo(with_code: bool) -> None:
    ctx = medical_context(medical_todos(with_code))
    result = await agent().recognize(ctx, sample("med_receipt"), USER, FakeGoogle())
    # 收據上也印了「診斷書費 Medical certificate fee」，仍要認成收據
    assert result.status == "recognized"
    assert result.document_kind == "D14 醫療費用收據"
    assert result.matched_todo_id == todo_of(ctx, "D14").id
    assert result.todo_complete
    assert result.found_fields == ["金額", "日期"]


async def test_photo_of_a_medical_receipt_is_read_by_ocr() -> None:
    content, _ = sample_file("med_receipt")
    # 照片要送 Azure；這裡用電子檔讀出的文字當 Azure 的回傳
    text = str(pymupdf.open(stream=content)[0].get_text("text"))
    ocr = FakeOcr([Line(t, 0.97) for t in text.splitlines() if t.strip()])
    result = await agent(ocr=ocr).recognize(
        medical_context(),
        upload(JPEG, "IMG_0153.jpg", "image/jpeg"),
        USER,
        FakeGoogle(),
    )
    assert ocr.calls == 1
    assert result.status == "recognized"
    assert result.document_kind == "D14 醫療費用收據"


async def test_certificate_without_diagnosis_is_incomplete_and_not_saved() -> None:
    drive = FakeDrive()
    result = await agent(drive=drive).recognize(
        medical_context(), sample("med_certificate_no_diagnosis"), USER, FakeGoogle()
    )
    assert result.status == "incomplete"
    assert result.missing == ["病名"]
    assert result.next_step == "請向醫院或診所索取載明病名的診斷書"
    assert result.found_fields == ["就診日期"]
    assert result.storage_path is None and not result.todo_complete
    assert not drive.files


async def test_receipt_without_amount_is_incomplete() -> None:
    result = await agent().recognize(
        medical_context(), sample("med_receipt_no_amount"), USER, FakeGoogle()
    )
    assert result.status == "incomplete"
    assert result.missing == ["金額"]
    assert result.next_step == "請向醫院或診所索取載明金額的醫療費用收據"


@pytest.mark.parametrize(
    "text",
    [
        "電子機票行程表暨收據\nITINERARY RECEIPT\n票號 999-2100000000\n總計 TWD 12,800",
        "示範便利商店\n收據\n2026-07-08\n礦泉水 25\n合計 64",
        "Hotel Receipt\nRoom charge THB 2,400\n2026-07-08",
    ],
    ids=["機票收據", "便利商店收據", "飯店收據"],
)
async def test_receipt_without_medical_words_is_not_a_medical_receipt(
    text: str,
) -> None:
    result = await agent().recognize(
        medical_context(), upload(pdf(text)), USER, FakeGoogle()
    )
    assert result.document_kind != "D14 醫療費用收據"
    assert result.status == "failed" and not result.todo_complete


async def test_passport_copy_ticks_the_identity_todo() -> None:
    ctx = medical_context()
    result = await agent().recognize(
        ctx, sample("med_passport_copy"), USER, FakeGoogle()
    )
    assert result.status == "recognized"
    assert result.document_kind == "D24 身分證明"
    assert result.matched_todo_id == todo_of(ctx, "D24").id
    assert result.todo_complete


async def test_taiwan_id_card_copy_ticks_the_identity_todo() -> None:
    ctx = medical_context()
    result = await agent().recognize(
        ctx,
        upload(pdf("中華民國國民身分證\n姓名 王小明\n統一編號 A123456789")),
        USER,
        FakeGoogle(),
    )
    assert result.document_kind == "D24 身分證明"
    assert result.matched_todo_id == todo_of(ctx, "D24").id


async def test_passport_number_on_a_certificate_does_not_make_it_an_identity_document() -> (
    None
):
    # 診斷書、收據上常印「Passport No.」，不能因此當成身分證明
    for name, kind in (
        ("med_certificate", "D13 診斷書"),
        ("med_receipt", "D14 醫療費用收據"),
    ):
        result = await agent().recognize(
            medical_context(), sample(name), USER, FakeGoogle()
        )
        assert result.document_kind == kind, name


async def test_medical_certificate_on_a_flight_delay_trip_is_not_matched() -> None:
    result = await agent().recognize(
        context(), sample("med_certificate"), USER, FakeGoogle()
    )
    assert result.status == "failed"
    assert result.failure == "not_matched"
    assert result.matched_todo_id is None


async def test_existing_flight_samples_are_not_mistaken_for_medical_documents() -> None:
    for name, kind in (
        ("ticket", "D02 機票"),
        ("claim_form", "D10 理賠申請書"),
    ):
        result = await agent().recognize(context(), sample(name), USER, FakeGoogle())
        assert result.document_kind == kind, name
