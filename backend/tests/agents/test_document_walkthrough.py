"""/dev 文件辨識逐步展示：用真正的 6 號跑，Drive 預設是假的，回傳不含原文個資。

「存到我的真 Drive」用假的 transport 代替 Google，不連網。
"""

import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import httpx
import pytest
from app.agents.document.reader import Line, ReadResult
from app.agents.document.storage import GoogleDrive
from app.agents.document.walkthrough import sample_file, walkthrough
from app.agents.registry import get_google_access
from app.api.main import build_api_router
from app.api.routes import dev_document
from app.contracts import UploadedFile, UserContext
from app.core.google_oauth import DRIVE_SCOPE
from app.main import app
from app.models import GoogleGrant, Identity, User
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from tests.agents.document_helpers import DELAY_TEXT, pdf
from tests.google_support import use_google_settings

URL = "/dev/document-walkthrough"


def _states(body: dict) -> dict[str, str]:
    return {s["key"]: s["state"] for s in body["steps"]}


async def test_delay_certificate_walks_through_every_step(client: AsyncClient) -> None:
    text = DELAY_TEXT + "\n旅客姓名：王\n小明"
    res = await client.post(
        URL, files={"file": ("王小明_延誤證明.pdf", pdf(text), "application/pdf")}
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "recognized" and body["status_label"] == "通過"
    assert body["todo_complete"]
    assert [s["key"] for s in body["steps"]] == [
        "read",
        "privacy",
        "classify",
        "match",
        "check",
        "save",
        "complete",
    ]
    assert set(_states(body).values()) == {"ok"}
    assert body["saved_path"] == (
        "好險有你 理賠文件/日本 2026-07-05～07-10/班機延誤 2026-07-10/"
        "班機延誤_航空公司開立班機延誤／取消證明_1.pdf"
    )
    assert "小明" not in res.text  # 只回傳遮過的文字


async def test_without_grant_stops_at_saving(client: AsyncClient) -> None:
    res = await client.post(
        URL,
        files={"file": ("a.pdf", pdf(DELAY_TEXT), "application/pdf")},
        data={"has_grant": "false"},
    )
    body = res.json()
    assert body["status"] == "needs_review"
    assert _states(body)["save"] == "warn" and _states(body)["complete"] == "skip"
    assert body["saved_path"] is None


async def test_boarding_pass_plus_earlier_ticket_completes_the_todo(
    client: AsyncClient,
) -> None:
    alone = (
        await client.post(
            URL,
            files={"file": ("b.pdf", pdf("BOARDING PASS BR198"), "application/pdf")},
        )
    ).json()
    assert alone["status"] == "recognized" and not alone["todo_complete"]
    assert _states(alone)["complete"] == "warn"
    both = (
        await client.post(
            URL,
            files={"file": ("b.pdf", pdf("BOARDING PASS BR198"), "application/pdf")},
            data={"previous": ["D02 機票"]},
        )
    ).json()
    assert both["todo_complete"]
    assert both["saved_path"].endswith("_2.pdf")


async def test_delay_without_delay_period_stops_at_check(client: AsyncClient) -> None:
    res = await client.post(
        URL,
        files={"file": ("a.pdf", pdf("班機延誤證明\n航班 BR198"), "application/pdf")},
    )
    body = res.json()
    assert body["status"] == "incomplete"
    assert _states(body)["check"] == "fail"
    assert _states(body)["save"] == "skip"


async def test_broken_file_stops_at_reading(client: AsyncClient) -> None:
    body = (
        await client.post(
            URL, files={"file": ("x.pdf", b"%PDF-1.4", "application/pdf")}
        )
    ).json()
    assert body["status"] == "failed"
    assert _states(body)["read"] == "fail"
    assert _states(body)["privacy"] == "skip"


def test_not_registered_in_production() -> None:
    paths = {getattr(r, "path", "") for r in build_api_router("production").routes}
    assert "/dev/document-walkthrough" not in paths


async def test_every_sample_can_be_downloaded_and_walked(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 就算這台機器設定了 Azure，測試也不連外：照片一律當成沒設定 Azure
    monkeypatch.setattr(dev_document, "ocr_from_settings", lambda: None)
    samples = (await client.get("/dev/document-samples")).json()
    expected = {
        "delay": "recognized",
        "delay_missing": "recognized",  # 有寫延誤時數，算有延誤期間
        "delay_no_reason": "recognized",  # 沒寫原因只提醒，照樣通過
        "delay_no_period": "incomplete",  # 沒有延誤期間：不合格、不存檔
        "boarding_pass": "recognized",
        "ticket": "recognized",
        "boarding_proof": "recognized",
        "claim_form": "recognized",
        "receipt": "failed",  # 不是理賠文件：辨識失敗，不留檔（規格 v3.7）
        "baggage_delay": "failed",  # 行李延誤不屬於班機延誤的待辦：辨識失敗
        "ticket_boarding": "recognized",  # 同一份包含兩者，D02 可以完成
        "ticket_locked": "failed",  # 有密碼，讀不到字
        # 照片版要送 Azure 讀字；測試環境沒設定 Azure，停在第 1 步「不確定」
        "photo_boarding_pass": "needs_review",
        "photo_delay_glare": "needs_review",
        "photo_ticket_blurry": "needs_review",
        "photo_claim_form": "needs_review",
    }
    assert {s["name"] for s in samples} == set(expected)
    for s in samples:
        got = await client.get(f"/dev/document-samples/{s['name']}")
        photo = s["name"].startswith("photo_")
        kind = "image/jpeg" if photo else "application/pdf"
        assert got.headers["content-type"] == kind
        assert len(got.content) < 500 * 1024  # pre-commit 擋大檔
        name = f"{s['name']}.{'jpg' if photo else 'pdf'}"
        body = (
            await client.post(URL, files={"file": (name, got.content, kind)})
        ).json()
        if photo:
            assert {st["key"]: st["state"] for st in body["steps"]}["read"] == "warn"
        assert body["status"] == expected[s["name"]], s["name"]
        if s["name"] in ("receipt", "baggage_delay"):
            assert not body["todo_complete"] and body["saved_path"] is None
            assert body["status_label"] == "辨識失敗"
        if s["name"] == "delay_no_reason":
            assert body["todo_complete"] and "原因" in (body["reason"] or "")
        if s["name"] == "delay_no_period":
            assert body["saved_path"] is None and "延誤期間" in (body["reason"] or "")
        if s["name"] == "ticket_locked":
            assert body["status_label"] == "無法辨識"
        if s["name"] == "ticket_boarding":
            assert body["document_kind"] == "D02 機票及登機證"
            assert body["todo_complete"]
        for secret in (
            "陳怡君",
            "A223456789",
            "0912-345-678",
            "CHEN",
            "YICHUN",
            "復興南路",
        ):
            assert secret not in str(body), (s["name"], secret)


async def test_photo_is_sent_to_ocr_only_once() -> None:
    # 6 號的辨識與逐步展示共用同一次 OCR 結果，不會讀兩次
    calls: list[str] = []

    class FakeOcr:
        async def read(self, content: bytes, content_type: str) -> ReadResult:
            calls.append(content_type)
            return ReadResult(
                [Line("BOARDING PASS 登機證", 0.99), Line("ZZ198", 0.98)], "ocr"
            )

    jpg, kind = sample_file("photo_boarding_pass")
    body = await walkthrough(
        UploadedFile(file_name="p.jpg", content_type=kind, content=jpg),
        ocr=FakeOcr(),
        previous_kinds=[],
    )
    assert body.status == "recognized" and body.document_kind == "D02 登機證"
    assert calls == ["image/jpeg"]


class _UserGoogle:
    """假的 GoogleAccess：登入者已授權 Drive，平台建好的理賠資料夾是 platform-root。"""

    async def access_token(self, user: UserContext, scope: str) -> str | None:
        return "user-token"

    async def drive_folder_id(self, user: UserContext) -> str | None:
        return "platform-root"


@pytest.fixture
async def google_user(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[User]:
    """用 Google 登入的使用者（還沒授權 Drive）；這頁不需要登入，所以換的是 signed_in_user。"""
    use_google_settings(monkeypatch)
    user = User(email="carol@example.com", name="Carol")
    session.add(user)
    await session.commit()
    session.add(Identity(user_id=user.id, provider="google", provider_user_id="sub-1"))
    await session.commit()
    app.dependency_overrides[dev_document.signed_in_user] = lambda: user
    yield user
    app.dependency_overrides.pop(dev_document.signed_in_user, None)


async def _grant_drive(session: AsyncSession, user: User) -> None:
    session.add(
        GoogleGrant(
            user_id=user.id,
            scopes=["openid", DRIVE_SCOPE],
            refresh_token_encrypted=b"\x00\x01",
            granted_at=datetime.now(UTC),
            status="active",
        )
    )
    await session.commit()


async def test_real_drive_saves_to_the_users_drive(
    client: AsyncClient, session: AsyncSession, google_user: User
) -> None:
    await _grant_drive(session, google_user)
    calls: list[httpx.Request] = []
    content = pdf(DELAY_TEXT)

    def google(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer user-token"
        if request.method == "GET":
            return httpx.Response(200, json={"files": []})  # 資料夾都還沒有
        if "upload" in request.url.path:
            assert content in request.content  # 存的就是上傳的那份
            return httpx.Response(200, json={"id": "drive-file-1"})
        meta = json.loads(request.content)
        return httpx.Response(200, json={"id": f"folder-{meta['name']}"})

    app.dependency_overrides[get_google_access] = _UserGoogle
    app.dependency_overrides[dev_document.real_drive_storage] = lambda: GoogleDrive(
        transport=httpx.MockTransport(google)
    )
    assert (await client.get("/dev/document-drive")).json()["real_available"]

    res = await client.post(
        URL,
        files={"file": ("a.pdf", content, "application/pdf")},
        data={"use_real_drive": "true", "has_grant": "false"},  # 模擬授權不影響真 Drive
    )
    body = res.json()
    assert body["status"] == "recognized", body
    assert body["drive"] == "real" and body["drive_note"] is None
    assert body["drive_file_id"] == "drive-file-1"
    assert body["drive_file_url"] == "https://drive.google.com/file/d/drive-file-1/view"
    # 平台的理賠資料夾底下建「行程（測試台）→ 事故」兩層
    assert body["saved_path"] == (
        "好險有你 理賠文件/日本（測試台） 2026-07-05～07-10/班機延誤 2026-07-10/"
        "班機延誤_航空公司開立班機延誤／取消證明_1.pdf"
    )
    created = [
        json.loads(c.content)
        for c in calls
        if c.method == "POST" and "upload" not in c.url.path
    ]
    assert created[0]["parents"] == ["platform-root"]
    save = next(s for s in body["steps"] if s["key"] == "save")
    assert save["title"] == "存到我的 Google Drive" and save["state"] == "ok"
    outputs = {f["label"]: f for f in save["outputs"]}
    assert outputs["Drive 檔案編號"]["value"] == "drive-file-1"
    assert outputs["雲端收到的指紋"]["ok"] is True


async def test_real_drive_falls_back_to_fake_when_signed_out(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_google_settings(monkeypatch)
    choice = (await client.get("/dev/document-drive")).json()
    assert choice["real_available"] is False and choice["action"] == "login"
    assert "還沒登入" in choice["reason"]

    body = (
        await client.post(
            URL,
            files={"file": ("a.pdf", pdf(DELAY_TEXT), "application/pdf")},
            data={"use_real_drive": "true"},
        )
    ).json()
    assert body["status"] == "recognized"
    assert body["drive"] == "fake" and "還沒登入" in body["drive_note"]
    assert body["drive_file_url"] is None
    save = next(s for s in body["steps"] if s["key"] == "save")
    assert save["title"] == "存到 Drive（展示用的假雲端）"
    assert any(f["label"] == "為什麼用假雲端" for f in save["inputs"])


@pytest.mark.usefixtures("google_user")
async def test_real_drive_needs_drive_grant(client: AsyncClient) -> None:
    choice = (await client.get("/dev/document-drive")).json()
    assert choice["real_available"] is False and choice["action"] == "authorize"
    body = (
        await client.post(
            URL,
            files={"file": ("a.pdf", pdf(DELAY_TEXT), "application/pdf")},
            data={"use_real_drive": "true"},
        )
    ).json()
    assert body["drive"] == "fake" and "還沒授權" in body["drive_note"]


async def test_without_google_login_settings_only_fake_drive(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_google_settings(monkeypatch, GOOGLE_CLIENT_ID=None)
    choice = (await client.get("/dev/document-drive")).json()
    assert choice == {
        "real_available": False,
        "reason": "這個環境沒有設定 Google 登入，只能用假雲端",
        "action": None,
    }
