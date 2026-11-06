"""/dev 文件辨識逐步展示：用真正的 6 號跑，Drive 是假的，回傳不含原文個資。"""

import pytest
from app.agents.document.reader import Line, ReadResult
from app.agents.document.walkthrough import sample_file, walkthrough
from app.api.main import build_api_router
from app.api.routes import dev_document
from app.contracts import UploadedFile
from httpx import AsyncClient

from tests.agents.document_helpers import DELAY_TEXT, pdf

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
        "旅遊保險理賠/日本 2026-07-05～07-10/班機延誤 2026-07-10/"
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


async def test_draft_rules_can_be_applied(client: AsyncClient) -> None:
    res = await client.post(
        URL,
        files={"file": ("a.pdf", pdf("班機延誤證明\n航班 BR198"), "application/pdf")},
        data={"apply_draft_rules": "true"},
    )
    body = res.json()
    assert body["status"] == "failed"
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
        "delay_missing": "recognized",  # 草稿規則沒套用時不檢查欄位
        "boarding_pass": "recognized",
        "ticket": "recognized",
        "boarding_proof": "recognized",
        "claim_form": "recognized",
        "receipt": "needs_review",
        # 已知漏洞：行李延誤證明也有「延誤證明」，被當成班機延誤的 D01
        "baggage_delay": "recognized",
        "ticket_boarding": "needs_review",  # 機票與登機證關鍵字同分
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
