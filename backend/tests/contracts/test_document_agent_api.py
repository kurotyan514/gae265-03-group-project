"""正式 API 真的在用 6 號的 agent：AGENT_6_IMPL=document，走 `POST /incidents/{id}/documents`。

和 test_v2 不同，這裡不用假的 6 號：registry 依設定建出真正的 `DocumentAgent`
（`create_document_agent()`，和正式環境同一條路），只把 Google Drive、Google 授權與 OCR 換成假的。
"""

import logging

import pytest
from app.agents.document import recognizer
from app.api.routes import incidents
from app.core.config import settings
from app.models import IncidentDocument, Policy
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from tests.agents.document_helpers import DELAY_TEXT, FakeDrive, FakeGoogle, pdf

pytestmark = pytest.mark.usefixtures("user")

# 文件上的個資：不可出現在回應、錯誤訊息或 log（ADR-0009）
NAME, ID_NO = "王小明", "A123456789"
PERSONAL = f"\n被保險人：{NAME}\n身分證字號：{ID_NO}"


@pytest.fixture
def drive(monkeypatch: pytest.MonkeyPatch) -> FakeDrive:
    """正式設定（AGENT_6_IMPL=document、沒開假雲端），只把 Google 的服務換成假的。"""
    fake = FakeDrive()
    monkeypatch.setattr(settings, "AGENT_6_IMPL", "document")
    monkeypatch.setattr(settings, "DOCUMENT_DEV_FAKE_STORAGE", False)
    monkeypatch.setattr(recognizer, "GoogleDrive", lambda: fake)
    monkeypatch.setattr(recognizer, "ocr_from_settings", lambda model=None: None)
    monkeypatch.setattr(incidents, "get_google_access", FakeGoogle)
    return fake


async def start(client: AsyncClient, policy: Policy) -> str:
    created = await client.post(
        f"/policies/{policy.id}/incidents", json={"description": "班機延誤了"}
    )
    assert created.status_code == 201, created.text
    incident_id = created.json()["incident"]["incident_id"]
    for i in range(6):  # 和 5 號（假的）對話到列出待辦
        said = "班機延誤了六小時" if i == 0 else "不知道"
        body = (
            await client.post(
                f"/incidents/{incident_id}/messages", json={"content": said}
            )
        ).json()
        if body["reply"]["finished"]:
            return incident_id
    raise AssertionError("5 號一直沒結束")


async def upload(client: AsyncClient, incident_id: str, text: str):
    return await client.post(
        f"/incidents/{incident_id}/documents",
        files={"file": ("證明.pdf", pdf(text), "application/pdf")},
    )


async def delay_todo(client: AsyncClient, incident_id: str) -> dict:
    state = (await client.get(f"/incidents/{incident_id}")).json()
    return next(t for t in state["todos"] if "延誤" in t["title"])


def assert_no_personal(*texts: str) -> None:
    for text in texts:
        assert NAME not in text and ID_NO not in text


async def test_通過_真的存進雲端_對應待辦被勾(
    client: AsyncClient,
    session: AsyncSession,
    policy: Policy,
    drive: FakeDrive,
    caplog: pytest.LogCaptureFixture,
) -> None:
    incident_id = await start(client, policy)
    caplog.set_level(logging.DEBUG)

    response = await upload(client, incident_id, DELAY_TEXT + PERSONAL)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["recognition_status"] == "recognized"
    assert body["document_kind"].startswith("D01")
    todo = await delay_todo(client, incident_id)
    assert body["todo_id"] == todo["id"] and todo["is_done"] is True
    document = (await session.exec(select(IncidentDocument))).one()
    assert document.storage_path in drive.files  # 檔案真的存進（假）Drive
    assert_no_personal(response.text, caplog.text)


@pytest.mark.parametrize(
    ("case", "text", "status"),
    [
        ("辨識失敗", "這是一份和理賠無關的文件" + PERSONAL, "failed"),
        ("不合格", "班機延誤證明 Flight Delay Certificate" + PERSONAL, "incomplete"),
    ],
)
async def test_沒通過_不留檔案_待辦不勾(
    client: AsyncClient,
    session: AsyncSession,
    policy: Policy,
    drive: FakeDrive,
    caplog: pytest.LogCaptureFixture,
    case: str,
    text: str,
    status: str,
) -> None:
    incident_id = await start(client, policy)
    caplog.set_level(logging.DEBUG)

    response = await upload(client, incident_id, text)

    assert response.status_code == 201, (case, response.text)
    assert response.json()["recognition_status"] == status, case
    assert not drive.files, case
    documents = (await session.exec(select(IncidentDocument))).all()
    assert all(d.storage_path == "" for d in documents), case
    assert (await delay_todo(client, incident_id))["is_done"] is False
    assert_no_personal(response.text, caplog.text)


async def test_沒有_google_授權_不留檔案_待辦不勾(
    client: AsyncClient,
    session: AsyncSession,
    policy: Policy,
    drive: FakeDrive,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(incidents, "get_google_access", lambda: FakeGoogle(None))
    incident_id = await start(client, policy)
    caplog.set_level(logging.DEBUG)

    response = await upload(client, incident_id, DELAY_TEXT + PERSONAL)

    assert response.status_code == 201, response.text
    assert response.json()["recognition_status"] != "recognized"
    assert not drive.files
    documents = (await session.exec(select(IncidentDocument))).all()
    assert all(d.storage_path == "" for d in documents)
    assert (await delay_todo(client, incident_id))["is_done"] is False
    assert_no_personal(response.text, caplog.text)


async def test_存檔失敗_不留檔案_待辦不勾(
    client: AsyncClient,
    session: AsyncSession,
    policy: Policy,
    drive: FakeDrive,
    caplog: pytest.LogCaptureFixture,
) -> None:
    drive.fail = True
    incident_id = await start(client, policy)
    caplog.set_level(logging.DEBUG)

    response = await upload(client, incident_id, DELAY_TEXT + PERSONAL)

    assert response.status_code == 201, response.text
    assert response.json()["recognition_status"] != "recognized"
    assert not drive.files
    documents = (await session.exec(select(IncidentDocument))).all()
    assert all(d.storage_path == "" for d in documents)
    assert (await delay_todo(client, incident_id))["is_done"] is False
    assert_no_personal(response.text, caplog.text)
