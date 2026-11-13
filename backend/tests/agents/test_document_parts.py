"""6 號的零件：去識別化、Azure 回應解析、Drive REST、合格規範載入、註冊。都不連網。"""

import json
from pathlib import Path

import httpx
import pytest
from app.agents.document import DocumentAgent
from app.agents.document.privacy import FILE_NAME, deidentify_document_text
from app.agents.document.reader import AzureDocumentIntelligence, OcrFailed
from app.agents.document.rules import RuleSourceMissing, load_rules
from app.agents.document.storage import GoogleDrive, StorageFailed
from app.agents.registry import get_document_recognizer
from app.core.config import settings
from pydantic import SecretStr

# 去識別化（#65）


def test_name_split_across_lines_is_masked() -> None:
    text = "被保險人：王\n小明\n航班 BR198\n王小\n明 先生"
    out = deidentify_document_text(text)
    assert "小明" not in out and "王小" not in out
    assert "BR198" in out  # 不是個資的內容照原樣保留


def test_name_in_file_name_is_masked() -> None:
    out = deidentify_document_text(
        "上傳者 陳大文 的文件 陳大文_登機證.jpg", "陳大文_登機證.jpg"
    )
    assert "陳大文" not in out
    assert FILE_NAME in out


def test_file_name_that_is_only_a_document_word_does_not_mask_content() -> None:
    out = deidentify_document_text("旅行平安保險理賠申請書", "申請書.pdf")
    assert out == "旅行平安保險理賠申請書"


def test_traveler_label_and_airline_name_format_are_masked() -> None:
    out = deidentify_document_text(
        "搭機證明\n旅客：王小明\n乘客 : 陳大文\nWANG/XIAOMING MR\nEVA AIR BOARDING PASS"
    )
    for secret in ("王小明", "陳大文", "WANG/XIAOMING"):
        assert secret not in out
    assert "EVA AIR BOARDING PASS" in out


def test_english_patient_labels_on_medical_documents_are_masked() -> None:
    # 泰國醫院、診所的單據多半是英文：姓名、護照號碼、病歷號（HN）都要遮
    out = deidentify_document_text(
        "MEDICAL CERTIFICATE\n"
        "Patient name: MS CHEN YICHUN\n"
        "Patient: Mr. Wang Xiaoming   HN: 69-000153\n"
        "Passport No.: X12345678\n"
        "Diagnosis: Acute gastroenteritis (ICD-10 A09)\n"
        "Date of visit: 08/07/2026"
    )
    for secret in ("CHEN", "YICHUN", "Wang", "Xiaoming", "X12345678", "69-000153"):
        assert secret not in out, secret
    assert "〔護照號碼〕" in out and "〔病歷號〕" in out
    # 判斷合格要用的病名與日期留著
    assert "Acute gastroenteritis" in out and "08/07/2026" in out


def test_passport_copy_name_and_machine_readable_zone_are_masked() -> None:
    out = deidentify_document_text(
        "護照影本 PASSPORT COPY\n姓：CHEN\n名：YICHUN\nSurname: LIN\n"
        "P<TWNCHEN<<YICHUN<<<<<<<<<<<<<<<<<<<<<<<<<<<\n"
        "X123456780TWN9203140F3101011<<<<<<<<<<<<<<00\n"
        "診斷病名：急性腸胃炎"
    )
    for secret in ("CHEN", "YICHUN", "LIN", "X123456780"):
        assert secret not in out, secret
    assert out.count("〔護照機讀碼〕") == 2
    assert "急性腸胃炎" in out  # 「病名：」不是姓名標籤


def test_handwritten_name_next_to_id_is_masked_everywhere() -> None:
    # 手寫申請書：格子裡的姓名沒有「標籤：」，戶名欄是「姓名 / 身分證字號」
    out = deidentify_document_text(
        "被保險人\n身分證號 A223456789\n陳怡君\n陳怡君 / A223456789\n陳怡君"
    )
    assert "陳怡君" not in out
    assert "身分證號" in out


def test_bank_account_is_masked() -> None:
    # 申請書的匯款帳號：手寫常分段寫，也常和「匯款帳號」標籤不在同一行
    out = deidentify_document_text(
        "匯款帳號\n1234-5678-9012\n帳號：0012 3456 7890 12\n金融機構代號 999"
    )
    assert "1234-5678-9012" not in out and "0012 3456 7890 12" not in out
    assert out.count("〔帳號〕") == 2
    assert "999" in out  # 銀行代號不是個資


def test_account_rule_does_not_eat_phones_dates_or_document_numbers() -> None:
    text = "手機 0912-345-678\n開立日期：2026-07-10\nNRT-DLY-20260710-0412\n航班 ZZ198"
    out = deidentify_document_text(text)
    assert "〔帳號〕" not in out
    assert "2026-07-10" in out and "ZZ198" in out


def test_birth_date_is_masked() -> None:
    out = deidentify_document_text(
        "出生79年 3月12日*身分證號\n出生日期：1990/03/12\n事故發生 115年7月10日"
    )
    for secret in ("79年", "3月12日", "1990/03/12"):
        assert secret not in out
    assert out.count("〔出生日期〕") == 2
    assert "115年7月10日" in out  # 事故日期要留著判斷理賠


def test_labeled_airline_name_is_masked_whole() -> None:
    out = deidentify_document_text("姓名：CHEN/YICHUN MS\nCHEN/YICHUN MS")
    assert "CHEN" not in out and "YICHUN" not in out


def test_handwritten_road_address_is_masked() -> None:
    out = deidentify_document_text(
        "台北\n大安\n復興南路一段 100 號 5 樓\n航段：東京成田 NRT"
    )
    assert "復興南路" not in out and "100 號" not in out
    assert "東京成田" in out


def test_common_personal_data_is_still_masked() -> None:
    out = deidentify_document_text("手機 0912-345-678 身分證 A123456789")
    assert "0912" not in out and "A123456789" not in out


# Azure Document Intelligence（#67）

ANALYZE = {
    "status": "succeeded",
    "analyzeResult": {
        "content": "班機延誤證明\n原因：天候",
        "pages": [
            {
                "words": [
                    {
                        "content": "班機延誤證明",
                        "confidence": 0.99,
                        "span": {"offset": 0, "length": 6},
                    },
                    {
                        "content": "原因：天候",
                        "confidence": 0.7,
                        "span": {"offset": 7, "length": 5},
                    },
                ],
                "lines": [
                    {"content": "班機延誤證明", "spans": [{"offset": 0, "length": 6}]},
                    {"content": "原因：天候", "spans": [{"offset": 7, "length": 5}]},
                ],
            }
        ],
        "styles": [{"isHandwritten": True, "spans": [{"offset": 7, "length": 5}]}],
    },
}


async def test_azure_result_is_parsed_line_by_line() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.method == "POST":
            assert request.headers["Ocp-Apim-Subscription-Key"] == "key"
            assert request.url.path.endswith("prebuilt-layout:analyze")
            return httpx.Response(
                202, headers={"Operation-Location": "https://di.example/result/1"}
            )
        return httpx.Response(200, json=ANALYZE)

    client = AzureDocumentIntelligence(
        "https://di.example/",
        "key",
        model="layout",
        transport=httpx.MockTransport(handler),
    )
    result = await client.read(b"jpeg", "image/jpeg")
    assert result.source == "ocr"
    assert [line.text for line in result.lines] == ["班機延誤證明", "原因：天候"]
    assert result.lines[0].confidence == 0.99 and not result.lines[0].handwritten
    assert result.lines[1].confidence == 0.7 and result.lines[1].handwritten
    assert len(calls) == 2


async def test_azure_rate_limit_waits_and_retries() -> None:
    # 免費方案每分鐘次數有限：送出與查結果都可能回 429，照 Retry-After 等一下再試
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        if calls.count(request.method) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        if request.method == "POST":
            return httpx.Response(
                202, headers={"Operation-Location": "https://di.example/result/1"}
            )
        return httpx.Response(200, json=ANALYZE)

    client = AzureDocumentIntelligence(
        "https://di.example",
        "key",
        transport=httpx.MockTransport(handler),
        poll_interval=0.0,
    )
    result = await client.read(b"jpeg", "image/jpeg")
    assert [line.text for line in result.lines] == ["班機延誤證明", "原因：天候"]
    assert calls == ["POST", "POST", "GET", "GET"]


async def test_azure_rate_limit_gives_up_after_timeout() -> None:
    client = AzureDocumentIntelligence(
        "https://di.example",
        "key",
        transport=httpx.MockTransport(
            lambda r: httpx.Response(429, headers={"Retry-After": "30"})
        ),
        timeout=0.0,
    )
    with pytest.raises(OcrFailed):
        await client.read(b"jpeg", "image/jpeg")


async def test_azure_error_is_reported_without_content() -> None:
    client = AzureDocumentIntelligence(
        "https://di.example",
        "key",
        transport=httpx.MockTransport(lambda r: httpx.Response(401)),
    )
    with pytest.raises(OcrFailed):
        await client.read(b"jpeg", "image/jpeg")


# Google Drive（#70）


async def test_drive_reuses_existing_folder_and_uploads() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"files": [{"id": "folder-1"}]})
        return httpx.Response(200, json={"id": "file-1"})

    drive = GoogleDrive(transport=httpx.MockTransport(handler))
    assert await drive.ensure_folder("tok", "好險有你 理賠文件", None) == "folder-1"
    assert (
        await drive.upload("tok", "folder-1", "D01-x.pdf", b"%PDF", "application/pdf")
        == "file-1"
    )
    assert all(r.headers["Authorization"] == "Bearer tok" for r in seen)
    assert b'"parents": ["folder-1"]' in seen[-1].content


async def test_drive_creates_missing_folder() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"files": []})
        body = json.loads(request.content)
        assert body["parents"] == ["root-1"]
        return httpx.Response(200, json={"id": "new-folder"})

    drive = GoogleDrive(transport=httpx.MockTransport(handler))
    assert await drive.ensure_folder("tok", "incident", "root-1") == "new-folder"


async def test_drive_rename_patches_only_the_name() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "file-1"})

    drive = GoogleDrive(transport=httpx.MockTransport(handler))
    await drive.rename("tok", "file-1", "班機延誤_機票_1.pdf")

    assert seen[0].method == "PATCH" and seen[0].url.path.endswith("/files/file-1")
    assert json.loads(seen[0].content) == {"name": "班機延誤_機票_1.pdf"}
    assert seen[0].headers["Authorization"] == "Bearer tok"


async def test_drive_rename_failure_raises_storage_failed() -> None:
    drive = GoogleDrive(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    with pytest.raises(StorageFailed):
        await drive.rename("tok", "gone", "n.pdf")


async def test_drive_move_adds_the_new_parent_and_removes_the_old_one() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"parents": ["incident-folder"]})
        return httpx.Response(200, json={"id": "file-1"})

    drive = GoogleDrive(transport=httpx.MockTransport(handler))
    await drive.move_to_folder("tok", "file-1", "trip-folder")

    assert seen[0].method == "GET" and seen[0].url.params["fields"] == "parents"
    assert seen[1].method == "PATCH" and seen[1].url.path.endswith("/files/file-1")
    assert seen[1].url.params["addParents"] == "trip-folder"
    assert seen[1].url.params["removeParents"] == "incident-folder"
    assert seen[1].headers["Authorization"] == "Bearer tok"


async def test_drive_move_does_nothing_when_already_in_the_folder() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"parents": ["trip-folder"]})

    drive = GoogleDrive(transport=httpx.MockTransport(handler))
    await drive.move_to_folder("tok", "file-1", "trip-folder")

    assert [r.method for r in seen] == ["GET"]


async def test_drive_move_failure_raises_storage_failed() -> None:
    drive = GoogleDrive(transport=httpx.MockTransport(lambda r: httpx.Response(403)))
    with pytest.raises(StorageFailed):
        await drive.move_to_folder("tok", "file-1", "trip-folder")


async def test_drive_download_reads_the_file_content() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"%PDF-1.4")

    drive = GoogleDrive(transport=httpx.MockTransport(handler))
    assert await drive.download("tok", "file-1") == b"%PDF-1.4"
    assert seen[0].url.path.endswith("/files/file-1")
    assert seen[0].url.params["alt"] == "media"


async def test_drive_delete_is_permanent_and_ignores_missing_files() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(204 if request.url.path.endswith("file-1") else 404)

    drive = GoogleDrive(transport=httpx.MockTransport(handler))
    await drive.delete("tok", "file-1")
    await drive.delete("tok", "gone")  # 已經不在：算成功
    assert [r.method for r in seen] == ["DELETE", "DELETE"]  # 刪除，不是移到垃圾桶


async def test_drive_delete_failure_raises_storage_failed() -> None:
    drive = GoogleDrive(transport=httpx.MockTransport(lambda r: httpx.Response(403)))
    with pytest.raises(StorageFailed):
        await drive.delete("tok", "file-1")


async def test_drive_failure_raises_storage_failed() -> None:
    drive = GoogleDrive(transport=httpx.MockTransport(lambda r: httpx.Response(403)))
    with pytest.raises(StorageFailed):
        await drive.upload("tok", "f", "n.pdf", b"x", "application/pdf")


# 合格規範（#69）


def test_shipped_rules_load_and_have_sources() -> None:
    rules = load_rules()
    assert rules and all(r.source_file and r.source_quote for r in rules)


def test_rule_without_source_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "rules.json"
    path.write_text(
        json.dumps(
            {
                "rules": [
                    {
                        "code": "D01",
                        "field": "x",
                        "label": "x",
                        "pattern": "x",
                        "source": {
                            "file": "backend/data/config/incident_catalog.json",
                            "quote": "不存在的句子",
                        },
                        "verified": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(RuleSourceMissing):
        load_rules(path)


# 註冊


def test_registered_as_document(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "AGENT_6_IMPL", "document")
    assert isinstance(get_document_recognizer(), DocumentAgent)


# 資料夾與檔名（#70、規格書 R8）


def test_folder_names_without_destination_or_dates_still_work() -> None:
    from app.agents.document.storage import incident_folder_name, trip_folder_name

    from tests.agents.document_helpers import context

    ctx = context().model_copy(
        update={"destination": None, "occurred_at": None, "incident_type_name": None}
    )
    ctx = ctx.model_copy(
        update={
            "policy": ctx.policy.model_copy(
                update={"start_date": None, "end_date": None}
            )
        }
    )
    assert trip_folder_name(ctx) == "行程"
    assert incident_folder_name(ctx) == "事故"


def test_slashes_in_names_are_made_safe() -> None:
    from app.agents.document.storage import document_file_name, trip_folder_name

    from tests.agents.document_helpers import context, todo

    ctx = context().model_copy(update={"destination": "東京/大阪"})
    assert "/" not in trip_folder_name(ctx)
    name = document_file_name(ctx, "D01", todo("請取得 A/B 證明"), "image/jpeg")
    assert name == "班機延誤_取得 A／B 證明_1.jpg"


# 開發用假存檔（DOCUMENT_DEV_FAKE_STORAGE）


async def test_dev_fake_storage_lets_the_flow_pass_without_google(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agents.document import create_document_agent
    from app.agents.document.storage import DevFakeDrive

    from tests.agents.document_helpers import (
        DELAY_TEXT,
        USER,
        FakeGoogle,
        context,
        pdf,
        upload,
    )

    monkeypatch.setattr(settings, "DOCUMENT_DEV_FAKE_STORAGE", True)
    agent = create_document_agent()
    assert isinstance(agent.drive, DevFakeDrive)
    result = await agent.recognize(
        context(), upload(pdf(DELAY_TEXT)), USER, FakeGoogle(token=None)
    )
    assert result.status == "recognized"
    assert result.storage_path and result.storage_path.startswith("dev-fake-file-")
    assert agent.drive.saved == [
        "好險有你 理賠文件/日本 2026-11-01～11-10/班機延誤 2026-11-08/"
        "班機延誤_航空公司開立班機延誤／取消證明_1.pdf"
    ]


def test_dev_fake_storage_is_refused_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agents.document import create_document_agent

    monkeypatch.setattr(settings, "DOCUMENT_DEV_FAKE_STORAGE", True)
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    with pytest.raises(RuntimeError):
        create_document_agent()


def test_real_drive_is_used_by_default() -> None:
    from app.agents.document import create_document_agent

    assert isinstance(create_document_agent().drive, GoogleDrive)


def test_default_agent_matches_the_production_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agents.document import create_document_agent

    monkeypatch.setattr(settings, "DOCUMENT_FIELD_CONFIDENCE", 0.65)
    monkeypatch.setattr(settings, "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT", "https://x")
    monkeypatch.setattr(settings, "AZURE_DOCUMENT_INTELLIGENCE_API_KEY", SecretStr("k"))
    monkeypatch.setattr(settings, "AZURE_DOCUMENT_INTELLIGENCE_MODEL", "layout")
    agent = create_document_agent()
    assert agent.threshold == 0.65
    assert agent.dev_token is None and agent.classify_fallback is None
    assert isinstance(agent.ocr, AzureDocumentIntelligence)
    assert agent.ocr.model == "layout"
    assert [r.field for r in agent.rules] == [r.field for r in load_rules()]


def test_overrides_only_change_what_is_given(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.agents.document import create_document_agent

    from tests.agents.document_helpers import FakeDrive

    monkeypatch.setattr(settings, "DOCUMENT_DEV_FAKE_STORAGE", True)
    monkeypatch.setattr(settings, "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT", "https://x")
    monkeypatch.setattr(settings, "AZURE_DOCUMENT_INTELLIGENCE_API_KEY", SecretStr("k"))
    drive = FakeDrive()
    agent = create_document_agent(drive=drive, ocr_model="layout")
    assert agent.drive is drive
    # 換了 Drive 就不帶開發用 token：授權由呼叫端給，才測得到「沒有授權」
    assert agent.dev_token is None
    assert isinstance(agent.ocr, AzureDocumentIntelligence)
    assert agent.ocr.model == "layout"
    assert create_document_agent(ocr=None).ocr is None
    assert create_document_agent(rules=[]).rules == []


def test_overrides_do_not_lift_the_production_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agents.document import create_document_agent

    from tests.agents.document_helpers import FakeDrive

    monkeypatch.setattr(settings, "DOCUMENT_DEV_FAKE_STORAGE", True)
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    with pytest.raises(RuntimeError):
        create_document_agent(drive=FakeDrive())
