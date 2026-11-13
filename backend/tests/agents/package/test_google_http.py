"""7 號真的連 Google 的轉接器：從 Drive 取檔、用 Gmail 寄信（規格：docs/specs/agent-7-package.md「模組」）。

用 httpx.MockTransport 當假的網路：檢查送給 Google 的內容，並模擬 Google 的回應，不連網路（ADR-0020）。
"""

from collections.abc import Callable

import httpx
import pytest
from app.agents.package import DriveFile, GmailDraft, GoogleApiError
from app.agents.package.google_http import HttpGoogleApi

Handler = Callable[[httpx.Request], httpx.Response]


def _api(handler: Handler) -> tuple[HttpGoogleApi, list[httpx.Request]]:
    sent: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return handler(request)

    return HttpGoogleApi(transport=httpx.MockTransport(record)), sent


def _drive(request: httpx.Request) -> httpx.Response:
    """假的 Drive：只有 file-1 這個檔案。"""
    if request.url.path != "/drive/v3/files/file-1":
        return httpx.Response(404, json={"error": {"code": 404, "status": "NOT_FOUND"}})
    if request.url.params.get("alt") == "media":
        return httpx.Response(200, content=b"%PDF content")
    return httpx.Response(
        200, json={"name": "班機延誤_機票及登機證_1.pdf", "mimeType": "application/pdf"}
    )


def _status(code: int) -> Handler:
    return lambda request: httpx.Response(code, json={"error": {"code": code}})


# ---- 從 Drive 取檔 ----


async def test_取檔回傳Drive上的檔名_類型與內容() -> None:
    api, _ = _api(_drive)

    file = await api.fetch_file("drive-token", "file-1")

    assert file == DriveFile(
        name="班機延誤_機票及登機證_1.pdf",
        mime_type="application/pdf",
        content=b"%PDF content",
    )


async def test_取檔用Drive的授權_先讀檔名再讀內容() -> None:
    api, sent = _api(_drive)

    await api.fetch_file("drive-token", "file-1")

    assert [r.method for r in sent] == ["GET", "GET"]
    assert all(r.url.host == "www.googleapis.com" for r in sent)
    assert all(r.headers["Authorization"] == "Bearer drive-token" for r in sent)
    assert sent[0].url.params["fields"] == "name,mimeType,trashed"
    assert sent[1].url.params["alt"] == "media"


async def test_檔案編號裡的特殊字元會編碼_不會改到別的網址() -> None:
    api, sent = _api(_status(404))

    with pytest.raises(GoogleApiError):
        await api.fetch_file("drive-token", "../../gmail/v1/x?y")

    assert sent[0].url.host == "www.googleapis.com"
    assert sent[0].url.raw_path.startswith(b"/drive/v3/files/..%2F..%2Fgmail")


@pytest.mark.parametrize(
    ("code", "kind"),
    [
        (404, "not_found"),
        (401, "unauthorized"),
        (403, "unauthorized"),
        (500, "unavailable"),
    ],
)
async def test_Drive回錯誤時丟出錯誤類別(code: int, kind: str) -> None:
    api, _ = _api(_status(code))

    with pytest.raises(GoogleApiError) as error:
        await api.fetch_file("drive-token", "file-1")

    assert error.value.kind == kind


async def test_檔案在垃圾桶時丟出trashed_不讀內容() -> None:
    # 7-2：Drive 刪除檔案是移到垃圾桶，用檔案編號還讀得到
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"name": "a.pdf", "mimeType": "application/pdf", "trashed": True}
        )

    api, sent = _api(handler)

    with pytest.raises(GoogleApiError) as error:
        await api.fetch_file("drive-token", "file-1")

    assert error.value.kind == "trashed"
    assert len(sent) == 1


async def test_讀到檔名但讀內容失敗時也丟出錯誤() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("alt") == "media":
            return httpx.Response(500)
        return _drive(request)

    api, _ = _api(handler)

    with pytest.raises(GoogleApiError) as error:
        await api.fetch_file("drive-token", "file-1")

    assert error.value.kind == "unavailable"


async def test_Drive回應缺少檔名時算暫時連不上() -> None:
    api, _ = _api(
        lambda request: httpx.Response(200, json={"mimeType": "application/pdf"})
    )

    with pytest.raises(GoogleApiError) as error:
        await api.fetch_file("drive-token", "file-1")

    assert error.value.kind == "unavailable"


async def test_連不上Google時算暫時連不上_錯誤訊息不含token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    api, _ = _api(handler)

    with pytest.raises(GoogleApiError) as error:
        await api.fetch_file("drive-token", "file-1")

    assert error.value.kind == "unavailable"
    assert "drive-token" not in str(error.value)


# ---- 用 Gmail 寄信 ----

MESSAGE = b"From: owner@example.com\r\nTo: claims@example.com\r\n\r\nbody"


def _gmail(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"id": "message-id-1", "threadId": "thread-1"})


async def test_寄信回傳信件編號() -> None:
    api, _ = _api(_gmail)

    assert await api.send_message("gmail-token", MESSAGE) == "message-id-1"


async def test_寄信用Gmail的授權_把整封信原樣上傳() -> None:
    # 用上傳的寫法，附件大也寄得出去（不用把信轉成 base64 放在 JSON 裡）
    api, sent = _api(_gmail)

    await api.send_message("gmail-token", MESSAGE)

    (request,) = sent
    assert request.method == "POST"
    assert request.url.host == "gmail.googleapis.com"
    assert request.url.path == "/upload/gmail/v1/users/me/messages/send"
    assert request.url.params["uploadType"] == "media"
    assert request.headers["Authorization"] == "Bearer gmail-token"
    assert request.headers["Content-Type"] == "message/rfc822"
    assert request.content == MESSAGE


@pytest.mark.parametrize(
    ("code", "kind"),
    [
        (401, "unauthorized"),
        (403, "unauthorized"),
        (429, "unavailable"),
        (500, "unavailable"),
    ],
)
async def test_Gmail回錯誤時丟出錯誤類別(code: int, kind: str) -> None:
    api, _ = _api(_status(code))

    with pytest.raises(GoogleApiError) as error:
        await api.send_message("gmail-token", MESSAGE)

    assert error.value.kind == kind
    assert "gmail-token" not in str(error.value)


def _gmail_draft(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200, json={"id": "draft-id-1", "message": {"id": "m1", "threadId": "t1"}}
    )


async def test_建立草稿回傳草稿編號與草稿裡那封信的編號() -> None:
    api, _ = _api(_gmail_draft)

    assert await api.create_draft("gmail-token", MESSAGE) == GmailDraft(
        id="draft-id-1", message_id="m1"
    )


async def test_建立草稿的回應缺信件編號時當成連不上() -> None:
    api, _ = _api(lambda _request: httpx.Response(200, json={"id": "draft-id-1"}))

    with pytest.raises(GoogleApiError) as error:
        await api.create_draft("gmail-token", MESSAGE)

    assert error.value.kind == "unavailable"


async def test_建立草稿用Gmail的授權_把整封信原樣上傳() -> None:
    api, sent = _api(_gmail_draft)

    await api.create_draft("gmail-token", MESSAGE)

    (request,) = sent
    assert request.method == "POST"
    assert request.url.host == "gmail.googleapis.com"
    assert request.url.path == "/upload/gmail/v1/users/me/drafts"
    assert request.url.params["uploadType"] == "media"
    assert request.headers["Authorization"] == "Bearer gmail-token"
    assert request.headers["Content-Type"] == "message/rfc822"
    assert request.content == MESSAGE


@pytest.mark.parametrize(
    ("code", "kind"),
    [
        (401, "unauthorized"),
        (403, "unauthorized"),
        (404, "unavailable"),
        (500, "unavailable"),
    ],
)
async def test_建立草稿時Gmail回錯誤丟出錯誤類別(code: int, kind: str) -> None:
    api, _ = _api(_status(code))

    with pytest.raises(GoogleApiError) as error:
        await api.create_draft("gmail-token", MESSAGE)

    assert error.value.kind == kind
    assert "gmail-token" not in str(error.value)


# ---- 查檔案還在不在（契約 v2.8 的 build 用）----


def _metadata(body: dict) -> Handler:
    return lambda _request: httpx.Response(200, json=body)


async def test_查檔案狀態只讀資訊_不下載內容() -> None:
    api, sent = _api(_metadata({"trashed": False}))

    assert await api.file_status("drive-token", "file-1") == "ok"

    (request,) = sent
    assert request.url.path == "/drive/v3/files/file-1"
    assert request.url.params["fields"] == "trashed"
    assert "alt" not in request.url.params
    assert request.headers["Authorization"] == "Bearer drive-token"


async def test_查檔案狀態_在垃圾桶回trashed_找不到回not_found() -> None:
    trashed, _ = _api(_metadata({"trashed": True}))
    missing, _ = _api(_status(404))

    assert await trashed.file_status("drive-token", "file-1") == "trashed"
    assert await missing.file_status("drive-token", "file-1") == "not_found"


@pytest.mark.parametrize(
    ("code", "kind"),
    [(401, "unauthorized"), (403, "unauthorized"), (500, "unavailable")],
)
async def test_查檔案狀態時Drive回錯誤丟出錯誤類別(code: int, kind: str) -> None:
    api, _ = _api(_status(code))

    with pytest.raises(GoogleApiError) as error:
        await api.file_status("drive-token", "file-1")

    assert error.value.kind == kind
