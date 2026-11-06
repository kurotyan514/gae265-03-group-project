"""合訂本拆分清單的 API：上傳、確認、沿用（票 #95 第二步，上傳 API 為接縫）。

用真實的泰安合訂本（4 個區段，最小的一份）；偵測與切分都是真的。
"""

import uuid

import pytest
from app.core.config import settings
from app.ingest.bundle_split import import_config_splits
from httpx import AsyncClient

pytestmark = pytest.mark.usefixtures("logged_in")

CODES = ["TAIAN01", "TAIAN02", "TAIAN03", ""]  # 第 4 個是恐怖主義附加條款，不收


def taian() -> bytes:
    return (settings.DATA_DIR / "clauses" / "taian.pdf").read_bytes()


async def upload(client: AsyncClient, name: str = "taian.pdf", **form) -> dict:
    response = await client.post(
        "/ingest/bundles",
        files={"file": (name, taian(), "application/pdf")},
        data={"company": "泰安產物", **form},
    )
    assert response.status_code == 201, response.text
    return response.json()


def fill_in(split: dict) -> dict:
    """照手寫清單的樣子填完：三個險種填代碼，最後一個標成不收。"""
    body = {k: split[k] for k in ("company", "loose_article")}
    body["sections"] = [
        {**s, "code": code, "skip": code == ""}
        for s, code in zip(split["sections"], CODES, strict=True)
    ]
    return body


async def test_上傳後偵測各險種起點_存成草稿(client: AsyncClient) -> None:
    split = await upload(client)

    assert split["status"] == "draft"
    assert split["reused"] is False
    assert [s["page"] for s in split["sections"]] == [1, 5, 6, 11]
    assert all(s["code"] == "" for s in split["sections"])  # 代碼等管理者填
    assert all(s["preview"] for s in split["sections"])  # 附上標題後的前幾行


async def test_內容相同的檔案沿用已存的清單_換檔名也算(client: AsyncClient) -> None:
    first = await upload(client)

    again = await upload(client, name="改了名字.pdf")

    assert again["reused"] is True
    assert again["id"] == first["id"]


async def test_設定檔匯入的已確認清單_上傳同一份直接沿用(
    client: AsyncClient, session
) -> None:
    await import_config_splits(session)

    split = await upload(client)

    assert split["reused"] is True
    assert split["status"] == "confirmed"
    assert [s["code"] for s in split["sections"]][:3] == CODES[:3]


async def test_不是_PDF_與過大的檔案被拒絕(client: AsyncClient, monkeypatch) -> None:
    bad = await client.post(
        "/ingest/bundles", files={"file": ("a.pdf", b"not a pdf", "application/pdf")}
    )
    assert bad.status_code == 415
    monkeypatch.setattr(settings, "INGEST_MAX_UPLOAD_MB", 0)
    big = await client.post(
        "/ingest/bundles", files={"file": ("a.pdf", taian(), "application/pdf")}
    )
    assert big.status_code == 413


async def test_試切顯示每個區段的條數與章(client: AsyncClient) -> None:
    split = await upload(client)

    result = (await client.post(f"/ingest/bundles/{split['id']}/check")).json()

    assert result["ok"] is True
    first = result["sections"][0]
    assert first["articles"] > 0
    assert first["first_titles"]
    assert sum(c["articles"] for c in first["chapters"]) == first["articles"]


async def test_填完代碼後確認成功_之後列表看得到(client: AsyncClient) -> None:
    split = await upload(client)
    saved = await client.put(f"/ingest/bundles/{split['id']}", json=fill_in(split))
    assert saved.status_code == 200, saved.text

    confirmed = (await client.post(f"/ingest/bundles/{split['id']}/confirm")).json()

    assert confirmed["confirmed"] is True
    assert confirmed["problems"] == []
    assert confirmed["split"]["status"] == "confirmed"
    skipped = confirmed["split"]["sections"][3]
    assert skipped["skip"] is True
    assert skipped["code"].startswith("skip_")  # 不收的區段自動補代碼
    listed = (await client.get("/ingest/bundles")).json()
    assert [(i["id"], i["status"]) for i in listed] == [(split["id"], "confirmed")]


async def test_沒填代碼_代碼重複_確認會列出問題而不是通過(client: AsyncClient) -> None:
    split = await upload(client)

    empty = (await client.post(f"/ingest/bundles/{split['id']}/confirm")).json()
    assert empty["confirmed"] is False
    assert any("要填險種代碼" in p for p in empty["problems"])

    body = fill_in(split)
    body["sections"][1]["code"] = "TAIAN01"
    await client.put(f"/ingest/bundles/{split['id']}", json=body)
    dup = (await client.post(f"/ingest/bundles/{split['id']}/confirm")).json()
    assert dup["confirmed"] is False
    assert any("TAIAN01 重複" in p for p in dup["problems"])
    assert dup["split"]["status"] == "draft"


async def test_標題找不到的清單存不進去(client: AsyncClient) -> None:
    split = await upload(client)
    body = fill_in(split)
    body["sections"][0]["anchor"] = "根本不在這份 PDF 裡的標題"

    response = await client.put(f"/ingest/bundles/{split['id']}", json=body)

    assert response.status_code == 422
    assert "找不到" in response.json()["detail"]
    unchanged = (await client.get(f"/ingest/bundles/{split['id']}")).json()
    assert unchanged["sections"][0]["anchor"] != "根本不在這份 PDF 裡的標題"


async def test_改過已確認的清單回到草稿_要重新確認(client: AsyncClient) -> None:
    split = await upload(client)
    await client.put(f"/ingest/bundles/{split['id']}", json=fill_in(split))
    await client.post(f"/ingest/bundles/{split['id']}/confirm")
    body = fill_in(split)
    body["sections"][0]["name"] = "改過的名稱"

    saved = (await client.put(f"/ingest/bundles/{split['id']}", json=body)).json()

    assert saved["status"] == "draft"
    assert saved["sections"][0]["name"] == "改過的名稱"


async def test_不收的章不會算進條數(client: AsyncClient) -> None:
    split = await upload(client)
    await client.put(f"/ingest/bundles/{split['id']}", json=fill_in(split))
    before = (await client.post(f"/ingest/bundles/{split['id']}/check")).json()
    section = before["sections"][0]
    chapter = section["chapters"][0]

    body = fill_in(split)
    body["sections"][0]["exclude_chapters"] = [chapter["name"]]
    await client.put(f"/ingest/bundles/{split['id']}", json=body)
    after = (await client.post(f"/ingest/bundles/{split['id']}/check")).json()

    assert after["sections"][0]["articles"] == section["articles"] - chapter["articles"]
    excluded = [c for c in after["sections"][0]["chapters"] if c["excluded"]]
    assert [c["name"] for c in excluded] == [
        chapter["name"]
    ]  # 不收的章仍列出，可以再勾回來


async def test_偵測漏掉的區段可以手動補上(client: AsyncClient) -> None:
    split = await upload(client)
    body = fill_in(split)
    removed = body["sections"].pop(1)  # 假裝偵測漏掉第二個
    assert (
        await client.put(f"/ingest/bundles/{split['id']}", json=body)
    ).status_code == 200

    body["sections"].insert(1, {**removed, "preview": []})  # 管理者依頁碼與標題補回
    saved = await client.put(f"/ingest/bundles/{split['id']}", json=body)

    assert saved.status_code == 200
    assert (await client.post(f"/ingest/bundles/{split['id']}/check")).json()[
        "ok"
    ] is True


async def test_找不到的清單回_404(client: AsyncClient) -> None:
    assert (await client.get(f"/ingest/bundles/{uuid.uuid4()}")).status_code == 404
    assert (await client.get("/ingest/bundles/不是id")).status_code == 404
