"""6 號泰國醫療 demo（#233）：D13 診斷書、D14 醫療費用收據。

Azure、Drive 都是假的；範例文件由 samples/make_samples.py 產生（--medical）。
"""

import uuid
from datetime import UTC, date, datetime

import pymupdf
import pytest
from app.agents.document.privacy import deidentify_document_text
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
    "D25": ("after_return", "保險單或其謄本"),
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


@pytest.mark.parametrize(
    ("lines", "kind", "found"),
    [
        (
            [
                "ใบรับรองแพทย์",
                "คลินิกเดโม",
                "วันที่ตรวจ 8 ก.ค. 2569",
                "การวินิจฉัยโรค: กระเพาะอาหารอักเสบเฉียบพลัน",
            ],
            "D13 診斷書",
            ["病名", "就診日期"],
        ),
        (
            [
                "ใบเสร็จรับเงิน",
                "คลินิกเดโม",
                "วันที่ 8 ก.ค. 2569",
                "ค่าบริการทางการแพทย์ 800.00",
                "รวมทั้งสิ้น 1,450.00 บาท",
            ],
            "D14 醫療費用收據",
            ["金額", "日期"],
        ),
    ],
    ids=["純泰文診斷書", "純泰文收據"],
)
async def test_thai_only_documents_pass(
    lines: list[str], kind: str, found: list[str]
) -> None:
    # 只有泰文、日期寫成「8 ก.ค. 2569」（泰國佛曆）的單據
    ocr = FakeOcr([Line(t, 0.97) for t in lines])
    result = await agent(ocr=ocr).recognize(
        medical_context(),
        upload(JPEG, "IMG_0001.jpg", "image/jpeg"),
        USER,
        FakeGoogle(),
    )
    assert result.status == "recognized"
    assert result.document_kind == kind
    assert result.found_fields == found


async def test_handwritten_diagnosis_needs_the_user_to_confirm() -> None:
    # 醫師手寫的病名：照樣存檔，但請使用者確認內容
    ocr = FakeOcr(
        [
            Line("MEDICAL CERTIFICATE", 0.99),
            Line("Demo Clinic", 0.99),
            Line("Date of visit: 08/07/2026", 0.98),
            Line("Diagnosis: Acute gastroenteritis", 0.95, handwritten=True),
        ]
    )
    result = await agent(ocr=ocr).recognize(
        medical_context(),
        upload(JPEG, "IMG_0002.jpg", "image/jpeg"),
        USER,
        FakeGoogle(),
    )
    assert result.status == "needs_review"
    assert result.reason == "「病名」是手寫，請確認內容正確"


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


@pytest.mark.parametrize("name", ["med_passport_copy", "med_id_card_copy"])
async def test_identity_copies_tick_the_identity_todo(name: str) -> None:
    ctx = medical_context()
    result = await agent().recognize(ctx, sample(name), USER, FakeGoogle())
    assert result.status == "recognized"
    assert result.document_kind == "D24 身分證明"
    assert result.matched_todo_id == todo_of(ctx, "D24").id
    assert result.todo_complete


@pytest.mark.parametrize("name", ["med_passport_copy", "med_id_card_copy"])
def test_identity_copies_leave_no_personal_data_after_masking(name: str) -> None:
    content, _ = sample_file(name)
    text = str(pymupdf.open(stream=content)[0].get_text("text"))
    out = deidentify_document_text(text, f"{name}.pdf")
    for secret in ("陳怡君", "CHEN", "YI-CHUN", "A223456789", "X00000000", "示範路"):
        assert secret not in out, secret


async def test_e_policy_ticks_the_policy_todo() -> None:
    ctx = medical_context()
    result = await agent().recognize(ctx, sample("med_policy"), USER, FakeGoogle())
    assert result.status == "recognized"
    assert result.document_kind == "D25 保險單"
    assert result.matched_todo_id == todo_of(ctx, "D25").id
    assert result.todo_complete


@pytest.mark.parametrize("name", ["claim_form", "med_claim_form"])
async def test_claim_form_with_a_policy_number_field_is_not_a_policy(name: str) -> None:
    # 申請書上有「保單號碼」欄，不能因此當成保險單
    ctx = medical_context()
    result = await agent().recognize(ctx, sample(name), USER, FakeGoogle())
    assert result.document_kind == "D10 理賠申請書"
    assert result.matched_todo_id == todo_of(ctx, "D10").id


def test_medical_claim_form_leaves_no_name_or_id_after_masking() -> None:
    content, _ = sample_file("med_claim_form")
    text = str(pymupdf.open(stream=content)[0].get_text("text"))
    out = deidentify_document_text(text, "med_claim_form.pdf")
    for secret in ("陳怡君", "A223456789", "0912", "復興南路", "example.com"):
        assert secret not in out, secret


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


# 保險期間：demo 保單是 2026/07/05～07/12（medical_context）


@pytest.mark.parametrize(
    "visit",
    [
        "2026-07-08",
        "2026/7/8",
        "08/07/2026",  # 日/月/年（泰國、歐洲）
        "07/08/2026",  # 月/日/年（美國）：兩種讀法有一種在期間內就算
        "8 Jul 2026",
        "08 JUL 2026",
        "8 ก.ค. 2569",  # 泰國佛曆
        "08/07/2569 B.E.",
        "115年7月8日",  # 民國年
        "115/07/08",
    ],
)
async def test_visit_date_inside_the_policy_period_passes(visit: str) -> None:
    result = await agent().recognize(
        medical_context(),
        upload(
            pdf(
                f"MEDICAL CERTIFICATE\nDemo Clinic\nDate of visit: {visit}\n"
                "Diagnosis: Acute gastroenteritis"
            )
        ),
        USER,
        FakeGoogle(),
    )
    assert result.status == "recognized", visit
    assert result.reason is None


@pytest.mark.parametrize(
    ("name", "text"),
    [
        (
            "診斷書",
            "MEDICAL CERTIFICATE\nDemo Clinic\nDate of visit: 20/08/2026\n"
            "Diagnosis: Acute gastroenteritis",
        ),
        (
            "收據",
            "OFFICIAL RECEIPT\nDemo Clinic\nDate: 2026-06-30\nTotal: THB 1,450.00",
        ),
    ],
)
async def test_date_outside_the_policy_period_needs_the_user_to_confirm(
    name: str, text: str
) -> None:
    drive = FakeDrive()
    result = await agent(drive=drive).recognize(
        medical_context(), upload(pdf(text)), USER, FakeGoogle()
    )
    assert result.status == "needs_review", name
    assert result.reason and "保險期間" in result.reason
    # 不放文件內容：日期本身不寫進 reason
    assert "2026" not in result.reason
    assert not result.todo_complete
    assert result.storage_path in drive.files  # 先存成待確認，使用者確認後才算數


async def test_date_that_cannot_be_read_is_not_judged() -> None:
    # 「Date of visit: 上週三」讀不出日期：只檢查有沒有寫，不判斷期間
    result = await agent().recognize(
        medical_context(),
        upload(
            pdf(
                "MEDICAL CERTIFICATE\nDemo Clinic\nDate of visit: 3rd visit 2 times\n"
                "Diagnosis: Acute gastroenteritis"
            )
        ),
        USER,
        FakeGoogle(),
    )
    assert result.status == "recognized"
