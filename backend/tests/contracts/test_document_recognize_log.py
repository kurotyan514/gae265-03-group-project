"""理賠文件上傳 API 的耗時日誌（#289，ADR-0027）。

每次 `POST /incidents/{id}/documents` 記一筆 `document_recognize_ms`，
包含毫秒、辨識狀態、檔案類型、大小區間，且不含檔名與文件內容。
"""

import logging
import re

import app.main  # noqa: F401
import pytest
from app.contracts import ContractViolation
from app.contracts.fakes import FakeDocumentRecognizer
from app.models import Policy
from httpx import AsyncClient

pytestmark = pytest.mark.usefixtures("user")

LOG_PATTERN = re.compile(
    r"^document_recognize_ms=(?P<ms>\d+) "
    r"status=(?P<status>recognized|failed|needs_review|incomplete|error) "
    r"content_type=(?P<content_type>\S+) "
    r"size_bucket=(?P<size_bucket><1MB|1-5MB|5-10MB)$"
)


async def _ready_incident(client: AsyncClient, policy: Policy) -> str:
    created = await client.post(
        f"/policies/{policy.id}/incidents", json={"description": "班機延誤了"}
    )
    assert created.status_code == 201, created.text
    incident_id = created.json()["incident"]["incident_id"]
    for i in range(6):
        said = "班機延誤了六小時" if i == 0 else "不知道"
        res = await client.post(
            f"/incidents/{incident_id}/messages", json={"content": said}
        )
        assert res.status_code == 200, res.text
        if res.json()["reply"]["finished"]:
            return incident_id
    raise AssertionError("5 號一直沒結束")


def test_incidents_logger_effective_level_allows_info() -> None:
    assert (
        logging.getLogger("app.api.routes.incidents").getEffectiveLevel()
        <= logging.INFO
    )


@pytest.mark.parametrize(
    ("file_name", "content_type", "size_bytes", "expected_status", "expected_bucket"),
    [
        (
            "王小明_A123456789_延誤證明.pdf",
            "application/pdf",
            512,
            "recognized",
            "<1MB",
        ),
        (
            "王小明_A123456789_bad.jpg",
            "image/jpeg",
            1024 * 1024 + 100,
            "failed",
            "1-5MB",
        ),
        (
            "王小明_A123456789_待確認檔案.png",
            "image/png",
            5 * 1024 * 1024 + 100,
            "needs_review",
            "5-10MB",
        ),
        (
            "王小明_A123456789_缺頁資料.pdf",
            "application/pdf",
            2048,
            "incomplete",
            "<1MB",
        ),
    ],
)
async def test_upload_logs_recognize_ms_without_filename_or_content(
    client: AsyncClient,
    policy: Policy,
    caplog: pytest.LogCaptureFixture,
    file_name: str,
    content_type: str,
    size_bytes: int,
    expected_status: str,
    expected_bucket: str,
) -> None:
    incident_id = await _ready_incident(client, policy)
    secret_content = b"SECRET_DOC_CONTENT_0912345678_"
    payload = secret_content + b"x" * max(0, size_bytes - len(secret_content))

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="app.api.routes.incidents"):
        response = await client.post(
            f"/incidents/{incident_id}/documents",
            files={"file": (file_name, payload, content_type)},
        )

    assert response.status_code == 201, response.text
    assert response.json()["recognition_status"] == expected_status

    records = [
        r.getMessage()
        for r in caplog.records
        if "document_recognize_ms" in r.getMessage()
    ]
    assert len(records) == 1
    match = LOG_PATTERN.match(records[0])
    assert match is not None, f"日誌格式不符：{records[0]}"
    assert int(match.group("ms")) >= 0
    assert match.group("status") == expected_status
    assert match.group("content_type") == content_type
    assert match.group("size_bucket") == expected_bucket

    # 日誌不含檔名、文件內容與個資
    assert file_name not in caplog.text
    assert "王小明" not in caplog.text
    assert "A123456789" not in caplog.text
    assert "SECRET_DOC_CONTENT_0912345678" not in caplog.text


@pytest.mark.parametrize(
    ("raw_content_type", "expected_content_type"),
    [
        (
            "image/jpeg size_bucket=<1MB status=recognized; name=王小明_A123456789.pdf",
            "other",
        ),
        (
            "Application/PDF; name=王小明_A123456789.pdf",
            "application/pdf",
        ),
    ],
)
async def test_upload_sanitizes_malicious_content_type_in_log(
    client: AsyncClient,
    policy: Policy,
    caplog: pytest.LogCaptureFixture,
    raw_content_type: str,
    expected_content_type: str,
) -> None:
    incident_id = await _ready_incident(client, policy)
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="app.api.routes.incidents"):
        response = await client.post(
            f"/incidents/{incident_id}/documents",
            files={
                "file": (
                    "王小明_A123456789_延誤證明.pdf",
                    b"%PDF-1.4",
                    raw_content_type,
                )
            },
        )

    assert response.status_code == 201, response.text
    records = [
        r.getMessage()
        for r in caplog.records
        if "document_recognize_ms" in r.getMessage()
    ]
    assert len(records) == 1
    line = records[0]
    match = LOG_PATTERN.match(line)
    assert match is not None, f"日誌格式不符：{line}"
    assert match.group("content_type") == expected_content_type
    for key in ("document_recognize_ms=", "status=", "content_type=", "size_bucket="):
        assert line.count(key) == 1
    assert "王小明" not in caplog.text
    assert "A123456789" not in caplog.text


async def test_upload_logs_error_status_when_recognizer_raises_contract_violation(
    client: AsyncClient,
    policy: Policy,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incident_id = await _ready_incident(client, policy)

    class BrokenRecognizer(FakeDocumentRecognizer):
        async def recognize(self, ctx, file, user, google):
            raise ContractViolation("模擬辨識違反契約")

    monkeypatch.setattr(
        "app.api.routes.incidents.get_document_recognizer", lambda: BrokenRecognizer()
    )

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="app.api.routes.incidents"):
        response = await client.post(
            f"/incidents/{incident_id}/documents",
            files={
                "file": (
                    "王小明_A123456789_延誤證明.pdf",
                    b"%PDF-1.4",
                    "application/pdf",
                )
            },
        )

    assert response.status_code == 502
    records = [
        r.getMessage()
        for r in caplog.records
        if "document_recognize_ms" in r.getMessage()
    ]
    assert len(records) == 1
    match = LOG_PATTERN.match(records[0])
    assert match is not None, f"日誌格式不符：{records[0]}"
    assert int(match.group("ms")) >= 0
    assert match.group("status") == "error"
    assert match.group("content_type") == "application/pdf"
    assert match.group("size_bucket") == "<1MB"
    assert "王小明" not in caplog.text
    assert "A123456789" not in caplog.text
