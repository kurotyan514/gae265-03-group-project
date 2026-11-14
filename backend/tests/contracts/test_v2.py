"""契約 v2（提案 docs/agents/handoff/contract-v2-proposal.md）：平台端的行為。

走上傳與對話的 API；agent 用假實作，必要時換成回傳指定結果的版本。
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from app.contracts import CONTRACT_VERSION, Recognition
from app.contracts.fakes import FakeDocumentRecognizer
from app.models import IncidentDocument, IncidentTodo, Policy
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

pytestmark = pytest.mark.usefixtures("user")


async def start(client: AsyncClient, policy: Policy) -> str:
    created = await client.post(
        f"/policies/{policy.id}/incidents", json={"description": "班機延誤了"}
    )
    assert created.status_code == 201, created.text
    return created.json()["incident"]["incident_id"]


async def talk(client: AsyncClient, incident_id: str, text: str = "") -> dict:
    """和 5 號對話到結束（fake 問兩輪），回最後一次的事件快照。"""
    body: dict = {}
    for i in range(6):
        said = f"班機延誤了六小時 {text}" if i == 0 else f"不知道 {text}"
        response = await client.post(
            f"/incidents/{incident_id}/messages", json={"content": said}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        if body["reply"]["finished"]:
            return body["incident"]
    raise AssertionError("5 號一直沒結束")


async def upload(client: AsyncClient, incident_id: str, name: str):
    return await client.post(
        f"/incidents/{incident_id}/documents",
        files={"file": (name, b"%PDF-1.4", "application/pdf")},
    )


def test_契約版本是_2_13_0() -> None:
    assert CONTRACT_VERSION == "2.13.0"
    changelog = Path("docs/agents/handoff/contract-changelog.md").read_text()
    assert CONTRACT_VERSION in changelog.split("\n## ", 2)[1]  # 最新一筆寫著版本


# ---- context 帶出的新資料 ----


async def test_context_有事故類型清單_必問欄位與這張保單對應的保障(
    client: AsyncClient, policy: Policy
) -> None:
    incident = (await client.get(f"/incidents/{await start(client, policy)}")).json()

    types = {t["code"]: t for t in incident["event_types"]}
    assert "flight_delay" in types and "medical" in types
    assert [f["key"] for f in types["flight_delay"]["fields"]] == [
        "dep_plan",
        "dep_act",
        "reason",
    ]
    assert [f["key"] for f in incident["common_fields"]] == ["date", "place"]
    # 富邦進階型涵蓋整份「享樂個人海外旅行不便保險」，事故類型要對到裡面「班機延誤」那一章
    refs = {
        (c["insurance_code"], c["section"]) for c in types["flight_delay"]["coverages"]
    }
    assert any("班機延誤" in (s or "") for _, s in refs), refs


async def test_重大注意事項來自這個事件實際列出的文件(
    client: AsyncClient, policy: Policy
) -> None:
    incident_id = await start(client, policy)
    assert (await client.get(f"/incidents/{incident_id}")).json()["major_notices"] == []

    state = await talk(client, incident_id)

    # 機票及登機證（D02）的重大注意事項
    assert "單據要保留正本" in state["major_notices"]
    assert len(state["major_notices"]) <= 4


async def test_重大注意事項有事故層級的提醒_保單有日期就帶入_沒有就不顯示(
    client: AsyncClient, session: AsyncSession, policy: Policy
) -> None:
    # 保單沒有保險期間：含日期的提醒不顯示（寧可不顯示也不顯示錯的），其他提醒照樣有
    without = await talk(client, await start(client, policy))
    assert "知悉事故後五日內要通知保險公司" in without["major_notices"]
    assert not any("保險期間" in n for n in without["major_notices"])

    policy.start_date, policy.end_date = date(2026, 11, 1), date(2026, 11, 8)
    session.add(policy)
    await session.commit()
    with_dates = await talk(client, await start(client, policy))

    assert (
        "保險期間為 2026/11/01 到 2026/11/08，這段期間內發生的事故才適用"
        in with_dates["major_notices"]
    )
    assert len(with_dates["major_notices"]) <= 4


# ---- 依結論建立待辦與理賠申請書 ----


async def test_至少一項可能適用才建立待辦與理賠申請書(
    client: AsyncClient, policy: Policy
) -> None:
    incident_id = await start(client, policy)
    before = (await client.get(f"/incidents/{incident_id}")).json()
    assert before["todos"] == []  # 還沒判斷出類型

    state = await talk(client, incident_id)

    scopes = {
        t["document_code"]: t["scope"] for t in state["todos"] if t["document_code"]
    }
    # D02、D10 是共同文件（ADR-0029），掛在保單上；D01 是事件自己的
    assert scopes == {"D01": "incident", "D02": "policy", "D10": "policy"}
    d10 = next(t for t in state["todos"] if t["document_code"] == "D10")
    assert d10["requires_upload"] is True


async def test_保障都是不賠就不建立待辦也不建立理賠申請書(
    client: AsyncClient, policy: Policy
) -> None:
    incident_id = await start(client, policy)

    state = await talk(client, incident_id, "這個不理賠")

    assert state["incident_type_code"] == "flight_delay"
    assert state["todos"] == []
    assert {c["conclusion"] for c in state["clauses"]} == {"excluded"}


async def test_共同文件同一張保單只建一次(
    client: AsyncClient, session: AsyncSession, policy: Policy
) -> None:
    await talk(client, await start(client, policy))
    await talk(client, await start(client, policy))

    forms = (
        await session.exec(
            select(IncidentTodo).where(IncidentTodo.policy_id == policy.id)
        )
    ).all()
    assert sorted(t.document_code or "" for t in forms) == ["D02", "D10"]


# ---- 辨識結果 ----


async def test_不合格不存檔_待辦不算完成_要寫缺什麼(
    client: AsyncClient, session: AsyncSession, policy: Policy
) -> None:
    incident_id = await start(client, policy)
    await talk(client, incident_id)

    response = await upload(client, incident_id, "王小明_缺頁證明.pdf")

    assert response.status_code == 201, response.text
    assert response.json()["recognition_status"] == "incomplete"
    assert response.json()["reason"] == "缺少最後一頁"
    document = (await session.exec(select(IncidentDocument))).one()
    assert document.storage_path == ""  # 不合格的檔案不保留
    state = (await client.get(f"/incidents/{incident_id}")).json()
    assert not any(t["is_done"] for t in state["todos"])


async def test_不確定先存檔_檔案編號留著等使用者確認(
    client: AsyncClient, session: AsyncSession, policy: Policy
) -> None:
    incident_id = await start(client, policy)
    await talk(client, incident_id)

    response = await upload(client, incident_id, "a.pdf")

    assert response.json()["recognition_status"] == "needs_review"
    document = (await session.exec(select(IncidentDocument))).one()
    assert document.storage_path.startswith("fake-cloud/")
    assert document.confirmed_by_user is False


async def test_一項待辦可以收多份文件_齊了才算完成(
    client: AsyncClient, session: AsyncSession, policy: Policy
) -> None:
    incident_id = await start(client, policy)
    state = await talk(client, incident_id)
    first_todo = state["todos"][0]["id"]

    half = await upload(client, incident_id, "半份證明.pdf")  # 其中一份：還沒齊
    assert half.json()["todo_id"] == first_todo
    mid = (await client.get(f"/incidents/{incident_id}")).json()
    assert next(t for t in mid["todos"] if t["id"] == first_todo)["is_done"] is False

    full = await upload(client, incident_id, "另一份證明.pdf")  # 6 號說齊了
    assert full.json()["todo_id"] == first_todo
    end = (await client.get(f"/incidents/{incident_id}")).json()
    assert next(t for t in end["todos"] if t["id"] == first_todo)["is_done"] is True
    docs = (await session.exec(select(IncidentDocument))).all()
    assert len([d for d in docs if str(d.incident_todo_id) == first_todo]) == 2


async def test_資料庫不存使用者上傳時的原檔名(
    client: AsyncClient, session: AsyncSession, policy: Policy
) -> None:
    incident_id = await start(client, policy)
    await talk(client, incident_id)

    await upload(client, incident_id, "王小明_診斷證明.pdf")

    document = (await session.exec(select(IncidentDocument))).one()
    assert "王小明" not in document.file_name
    assert document.file_name.startswith("班機延誤_") and document.file_name.endswith(
        "_1.pdf"
    )


async def test_6_號沒給檔名時平台用文件代碼和序號補(
    client: AsyncClient,
    session: AsyncSession,
    policy: Policy,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class V1Recognizer(FakeDocumentRecognizer):
        async def recognize(self, ctx, file, user, google):  # type: ignore[override]
            result = await super().recognize(ctx, file, user, google)
            return result.model_copy(update={"stored_name": None})

    monkeypatch.setattr(
        "app.api.routes.incidents.get_document_recognizer", lambda: V1Recognizer()
    )
    incident_id = await start(client, policy)
    await talk(client, incident_id)

    await upload(client, incident_id, "王小明_診斷證明.pdf")

    document = (await session.exec(select(IncidentDocument))).one()
    assert document.file_name == "D01_1.pdf"


async def test_理賠申請書可以對到文件(
    client: AsyncClient,
    policy: Policy,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incident_id = await start(client, policy)
    state = await talk(client, incident_id)
    d10 = next(t for t in state["todos"] if t["document_code"] == "D10")

    class FormRecognizer(FakeDocumentRecognizer):
        async def recognize(self, ctx, file, user, google):  # type: ignore[override]
            return Recognition(
                status="recognized",
                matched_todo_id=uuid.UUID(d10["id"]),
                todo_complete=True,
                storage_path="fake-cloud/form",
            )

    monkeypatch.setattr(
        "app.api.routes.incidents.get_document_recognizer", lambda: FormRecognizer()
    )

    response = await upload(client, incident_id, "form.pdf")

    assert response.status_code == 201, response.text
    after = (await client.get(f"/incidents/{incident_id}")).json()
    form = next(t for t in after["todos"] if t["document_code"] == "D10")
    assert form["is_done"] is True and form["done_by"] == "agent"


# ---- 第 3 步：API ----


async def test_需上傳的待辦使用者也能自己勾_標未附文件_取消就清掉(
    client: AsyncClient, policy: Policy
) -> None:
    incident_id = await start(client, policy)
    state = await talk(client, incident_id)
    d10 = next(t for t in state["todos"] if t["document_code"] == "D10")
    assert d10["requires_upload"] is True

    ticked = await client.patch(
        f"/incidents/{incident_id}/todos/{d10['id']}", json={"is_done": True}
    )
    assert ticked.status_code == 200, ticked.text
    form = next(t for t in ticked.json()["todos"] if t["id"] == d10["id"])
    assert form["is_done"] and form["done_by"] == "user"
    assert form["without_document"] is True

    cleared = await client.patch(
        f"/incidents/{incident_id}/todos/{d10['id']}", json={"is_done": False}
    )
    form = next(t for t in cleared.json()["todos"] if t["id"] == d10["id"])
    assert not form["is_done"] and form["without_document"] is False


async def test_不需上傳的待辦勾選不會標未附文件(
    client: AsyncClient, policy: Policy
) -> None:
    incident_id = await start(client, policy)
    state = await talk(client, incident_id)
    extra = next(t for t in state["todos"] if not t["requires_upload"])  # 5 號加的待辦

    ticked = await client.patch(
        f"/incidents/{incident_id}/todos/{extra['id']}", json={"is_done": True}
    )

    done = next(t for t in ticked.json()["todos"] if t["id"] == extra["id"])
    assert done["is_done"] and done["without_document"] is False


async def test_上傳時指定待辦_辨識結果對到指定的那一項(
    client: AsyncClient, policy: Policy
) -> None:
    incident_id = await start(client, policy)
    state = await talk(client, incident_id)
    second = next(t for t in state["todos"] if t["document_code"] == "D02")

    response = await client.post(
        f"/incidents/{incident_id}/documents",
        files={"file": ("a證明.pdf", b"%PDF-1.4", "application/pdf")},
        data={"todo_id": second["id"]},
    )

    assert response.status_code == 201, response.text
    assert response.json()["todo_id"] == second["id"]
    after = (await client.get(f"/incidents/{incident_id}")).json()
    assert next(t for t in after["todos"] if t["id"] == second["id"])["is_done"]
    first = next(t for t in after["todos"] if t["document_code"] == "D01")
    assert not first["is_done"]  # 沒有被順位在前面的那一項吃掉


async def test_上傳回應帶出處理清單要的結果_打勾與追加(
    client: AsyncClient, policy: Policy
) -> None:
    incident_id = await start(client, policy)
    state = await talk(client, incident_id)
    d01 = next(t for t in state["todos"] if t["document_code"] == "D01")

    first = await client.post(
        f"/incidents/{incident_id}/documents",
        files={"file": ("a證明.pdf", b"%PDF-1.4", "application/pdf")},
        data={"todo_id": d01["id"]},
    )
    again = await client.post(
        f"/incidents/{incident_id}/documents",
        files={"file": ("b證明.pdf", b"%PDF-1.4", "application/pdf")},
        data={"todo_id": d01["id"]},
    )

    assert first.status_code == again.status_code == 201
    assert first.json()["todo_complete"] and not first.json()["appended"]
    # 同一項待辦已經完成後再傳一份：畫面顯示「已追加到已完成的待辦」
    assert again.json()["appended"]
    assert first.json()["failure"] is None and first.json()["found_fields"] == []


async def test_失敗的種類與判斷依據原樣帶出(
    client: AsyncClient, policy: Policy, monkeypatch: pytest.MonkeyPatch
) -> None:
    incident_id = await start(client, policy)
    await talk(client, incident_id)

    class NotMatched(FakeDocumentRecognizer):
        async def recognize(self, ctx, file, user, google):  # type: ignore[override]
            return Recognition(
                status="failed",
                failure="not_matched",
                reason="不屬於這個行程的任何待辦",
            )

    monkeypatch.setattr(
        "app.api.routes.incidents.get_document_recognizer", lambda: NotMatched()
    )
    response = await client.post(
        f"/incidents/{incident_id}/documents",
        files={"file": ("a.pdf", b"%PDF-1.4", "application/pdf")},
    )

    assert response.status_code == 201, response.text
    assert response.json()["failure"] == "not_matched"
    assert not response.json()["todo_complete"] and not response.json()["appended"]


async def test_候選待辦不屬於這個事件_被擋下(
    client: AsyncClient,
    session: AsyncSession,
    policy: Policy,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incident_id = await start(client, policy)
    await talk(client, incident_id)

    class StrangerCandidate(FakeDocumentRecognizer):
        async def recognize(self, ctx, file, user, google):  # type: ignore[override]
            return Recognition(
                status="needs_review",
                reason="請選擇",
                candidate_todo_ids=[uuid.uuid4()],
            )

    monkeypatch.setattr(
        "app.api.routes.incidents.get_document_recognizer", lambda: StrangerCandidate()
    )
    response = await client.post(
        f"/incidents/{incident_id}/documents",
        files={"file": ("a.pdf", b"%PDF-1.4", "application/pdf")},
    )

    assert response.status_code == 502
    assert (await session.exec(select(IncidentDocument))).all() == []


async def test_不合格的缺少項目與下一步原樣帶出(
    client: AsyncClient, policy: Policy, monkeypatch: pytest.MonkeyPatch
) -> None:
    incident_id = await start(client, policy)
    await talk(client, incident_id)

    class Incomplete(FakeDocumentRecognizer):
        async def recognize(self, ctx, file, user, google):  # type: ignore[override]
            return Recognition(
                status="incomplete",
                reason="看不到延誤期間",
                missing=["延誤期間"],
                next_step="請向航空公司索取載明延誤期間的延誤／取消證明",
            )

    monkeypatch.setattr(
        "app.api.routes.incidents.get_document_recognizer", lambda: Incomplete()
    )
    response = await client.post(
        f"/incidents/{incident_id}/documents",
        files={"file": ("a.pdf", b"%PDF-1.4", "application/pdf")},
    )

    assert response.status_code == 201, response.text
    assert response.json()["missing"] == ["延誤期間"]
    assert response.json()["next_step"].startswith("請向航空公司")


async def test_指定的待辦不存在_回_404_不辨識(
    client: AsyncClient, session: AsyncSession, policy: Policy
) -> None:
    incident_id = await start(client, policy)
    await talk(client, incident_id)

    response = await client.post(
        f"/incidents/{incident_id}/documents",
        files={"file": ("a.pdf", b"%PDF-1.4", "application/pdf")},
        data={"todo_id": str(uuid.uuid4())},
    )

    assert response.status_code == 404
    assert (await session.exec(select(IncidentDocument))).all() == []


async def test_辨識結果對到沒指定的待辦_被擋下(
    client: AsyncClient,
    session: AsyncSession,
    policy: Policy,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incident_id = await start(client, policy)
    state = await talk(client, incident_id)
    asked, other = state["todos"][0]["id"], state["todos"][1]["id"]

    class WrongTodo(FakeDocumentRecognizer):
        async def recognize(self, ctx, file, user, google):  # type: ignore[override]
            return Recognition(
                status="recognized",
                matched_todo_id=uuid.UUID(other),
                todo_complete=True,
                storage_path="x",
            )

    monkeypatch.setattr(
        "app.api.routes.incidents.get_document_recognizer", lambda: WrongTodo()
    )

    response = await client.post(
        f"/incidents/{incident_id}/documents",
        files={"file": ("a.pdf", b"%PDF-1.4", "application/pdf")},
        data={"todo_id": asked},
    )

    assert response.status_code == 502
    assert (await session.exec(select(IncidentDocument))).all() == []


async def test_使用者確認不確定的文件_對到自己選的待辦_沿用已存的檔案(
    client: AsyncClient, session: AsyncSession, policy: Policy
) -> None:
    incident_id = await start(client, policy)
    state = await talk(client, incident_id)
    document = (await upload(client, incident_id, "a.pdf")).json()  # 不確定，先存檔
    assert document["recognition_status"] == "needs_review"
    target = next(t for t in state["todos"] if t["document_code"] == "D02")

    response = await client.post(
        f"/incidents/{incident_id}/documents/{document['id']}/confirm",
        json={"todo_id": target["id"]},
    )

    assert response.status_code == 200, response.text
    confirmed = next(t for t in response.json()["todos"] if t["id"] == target["id"])
    assert confirmed["is_done"] and confirmed["done_by"] == "user"
    row = (await session.exec(select(IncidentDocument))).one()
    await session.refresh(row)
    assert row.confirmed_by_user is True and str(row.incident_todo_id) == target["id"]
    assert row.storage_path.startswith("fake-cloud/")  # 沿用先前存的檔案，沒有重傳
    # 7 號的附件包含使用者確認過的文件
    package = (await client.get(f"/incidents/{incident_id}/package")).json()
    assert len(package["attachments"]) == 1


async def test_選了待辦後重新檢查_通過才對上並勾起(
    client: AsyncClient, session: AsyncSession, policy: Policy
) -> None:
    incident_id = await start(client, policy)
    state = await talk(client, incident_id)
    document = (await upload(client, incident_id, "a.pdf")).json()
    assert document["recognition_status"] == "needs_review"
    target = next(t for t in state["todos"] if t["document_code"] == "D02")

    response = await client.post(
        f"/incidents/{incident_id}/documents/{document['id']}/recheck",
        json={"todo_id": target["id"]},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["recognition_status"] == "recognized" and body["todo_complete"]
    assert body["todo_id"] == target["id"]
    assert body["stored"] is True  # 沿用先存的檔案
    after = (await client.get(f"/incidents/{incident_id}")).json()
    ticked = next(t for t in after["todos"] if t["id"] == target["id"])
    assert ticked["is_done"] and ticked["done_by"] == "agent"  # 6 號檢查過才勾
    row = (await session.exec(select(IncidentDocument))).one()
    await session.refresh(row)
    assert row.recognition_status == "recognized" and row.confirmed_by_user


async def test_選了待辦後重新檢查_不合格就拿掉文件(
    client: AsyncClient,
    session: AsyncSession,
    policy: Policy,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incident_id = await start(client, policy)
    state = await talk(client, incident_id)
    document = (await upload(client, incident_id, "a.pdf")).json()
    target = next(t for t in state["todos"] if t["document_code"] == "D01")

    class Incomplete(FakeDocumentRecognizer):
        async def recheck(self, ctx, document, todo, user, google):  # type: ignore[override]
            return Recognition(
                status="incomplete",
                reason="看不到延誤期間",
                missing=["延誤期間"],
                next_step="請向航空公司索取載明延誤期間的延誤／取消證明",
            )

    monkeypatch.setattr(
        "app.api.routes.incidents.get_document_recognizer", lambda: Incomplete()
    )
    response = await client.post(
        f"/incidents/{incident_id}/documents/{document['id']}/recheck",
        json={"todo_id": target["id"]},
    )

    assert response.status_code == 200, response.text
    assert response.json()["recognition_status"] == "incomplete"
    assert response.json()["missing"] == ["延誤期間"]
    assert response.json()["stored"] is False  # 6 號已刪掉雲端的檔案
    assert (await session.exec(select(IncidentDocument))).all() == []
    after = (await client.get(f"/incidents/{incident_id}")).json()
    assert not next(t for t in after["todos"] if t["id"] == target["id"])["is_done"]


async def test_重新檢查回不合格卻留著檔案_被擋下(
    client: AsyncClient,
    session: AsyncSession,
    policy: Policy,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incident_id = await start(client, policy)
    state = await talk(client, incident_id)
    document = (await upload(client, incident_id, "a.pdf")).json()
    target = state["todos"][0]

    class KeepsFile(FakeDocumentRecognizer):
        async def recheck(self, ctx, document, todo, user, google):  # type: ignore[override]
            return Recognition(status="incomplete", reason="缺", storage_path="x")

    monkeypatch.setattr(
        "app.api.routes.incidents.get_document_recognizer", lambda: KeepsFile()
    )
    response = await client.post(
        f"/incidents/{incident_id}/documents/{document['id']}/recheck",
        json={"todo_id": target["id"]},
    )

    assert response.status_code == 502
    assert len((await session.exec(select(IncidentDocument))).all()) == 1  # 一筆都不動


async def test_選都不是_拿掉文件(
    client: AsyncClient, session: AsyncSession, policy: Policy
) -> None:
    incident_id = await start(client, policy)
    await talk(client, incident_id)
    document = (await upload(client, incident_id, "a.pdf")).json()

    response = await client.post(
        f"/incidents/{incident_id}/documents/{document['id']}/reject"
    )

    assert response.status_code == 200, response.text
    assert response.json()["documents"] == []
    assert (await session.exec(select(IncidentDocument))).all() == []


async def test_打開行程時清掉上次沒選的文件_這次上傳的不動(
    client: AsyncClient, session: AsyncSession, policy: Policy
) -> None:
    incident_id = await start(client, policy)
    await talk(client, incident_id)
    await upload(client, incident_id, "a.pdf")  # 需要你確認，沒選

    earlier = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    kept = await client.post(
        f"/incidents/{incident_id}/documents/discard-pending", json={"before": earlier}
    )
    assert kept.status_code == 200, kept.text
    assert len(kept.json()["documents"]) == 1  # 打開頁面之後才上傳的不清

    later = (datetime.now(UTC) + timedelta(seconds=5)).isoformat()
    cleared = await client.post(
        f"/incidents/{incident_id}/documents/discard-pending", json={"before": later}
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["documents"] == []
    assert (await session.exec(select(IncidentDocument))).all() == []


async def test_確認文件的各種錯誤(
    client: AsyncClient, session: AsyncSession, policy: Policy
) -> None:
    incident_id = await start(client, policy)
    state = await talk(client, incident_id)
    target = state["todos"][0]["id"]
    unsure = (await upload(client, incident_id, "a.pdf")).json()  # needs_review
    sure = (await upload(client, incident_id, "診斷.pdf")).json()  # recognized

    def confirm(doc_id: str, todo_id: str):
        return client.post(
            f"/incidents/{incident_id}/documents/{doc_id}/confirm",
            json={"todo_id": todo_id},
        )

    assert (await confirm(str(uuid.uuid4()), target)).status_code == 404  # 沒有這份文件
    assert (
        await confirm(unsure["id"], str(uuid.uuid4()))
    ).status_code == 404  # 沒有這項待辦
    assert (await confirm(sure["id"], target)).status_code == 409  # 不是「需人工確認」
    assert (await confirm(unsure["id"], target)).status_code == 200
    assert (await confirm(unsure["id"], target)).status_code == 409  # 已經確認過

    row = (
        await session.exec(
            select(IncidentDocument).where(
                IncidentDocument.id == uuid.UUID(unsure["id"])
            )
        )
    ).one()
    assert row.confirmed_by_user


async def test_沒有存檔的文件不能確認_要重傳(
    client: AsyncClient, session: AsyncSession, policy: Policy
) -> None:
    incident_id = await start(client, policy)
    state = await talk(client, incident_id)
    unsure = (await upload(client, incident_id, "a.pdf")).json()
    row = (await session.exec(select(IncidentDocument))).one()
    row.storage_path = ""  # 例如 6 號當時沒有 Drive 授權，沒辦法先存檔
    session.add(row)
    await session.commit()

    response = await client.post(
        f"/incidents/{incident_id}/documents/{unsure['id']}/confirm",
        json={"todo_id": state["todos"][0]["id"]},
    )

    assert response.status_code == 409
    assert "重新上傳" in response.json()["detail"]


def _recognition(case: str, todo_id: str) -> Recognition:
    """處理清單第 4 階段的五種情況：6 號回的結果（契約 document_agent.py）。"""
    match case:
        case "recognized":
            return Recognition(
                status="recognized",
                matched_todo_id=uuid.UUID(todo_id),
                todo_complete=True,
                storage_path="fake-cloud/ok",
            )
        case "incomplete":
            return Recognition(
                status="incomplete", reason="看不到延誤期間", missing=["延誤期間"]
            )
        case "unreadable":
            return Recognition(status="failed", failure="unreadable", reason="看不清楚")
        case "not_matched":
            return Recognition(
                status="failed", failure="not_matched", reason="不在待辦"
            )
        case "review_authorized":
            return Recognition(
                status="needs_review",
                reason="請選擇",
                storage_path="fake-cloud/pending",
            )
        case _:  # review_unsaved：沒有授權或存檔失敗，沒有檔案
            return Recognition(status="needs_review", reason="還沒有 Google 授權")


@pytest.mark.parametrize(
    ("case", "stored"),
    [
        ("recognized", True),
        ("incomplete", False),
        ("unreadable", False),
        ("not_matched", False),
        ("review_authorized", True),
        ("review_unsaved", False),
    ],
)
async def test_上傳回應的_stored_看辨識結果有沒有存放位置(
    client: AsyncClient,
    policy: Policy,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    stored: bool,
) -> None:
    incident_id = await start(client, policy)
    state = await talk(client, incident_id)
    todo_id = state["todos"][0]["id"]

    class Fixed(FakeDocumentRecognizer):
        async def recognize(self, ctx, file, user, google):  # type: ignore[override]
            return _recognition(case, todo_id)

    monkeypatch.setattr(
        "app.api.routes.incidents.get_document_recognizer", lambda: Fixed()
    )
    response = await upload(client, incident_id, "a.pdf")

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["stored"] is stored
    assert "storage_path" not in body  # 只說有沒有存，不洩漏位置


class _NoRecheck:
    """沒有實作選配「重新檢查」的辨識器：只有 recognize，其餘委派給假的。"""

    def __init__(self) -> None:
        self._inner = FakeDocumentRecognizer()

    async def recognize(self, ctx, file, user, google):  # noqa: ANN001, ANN201
        return await self._inner.recognize(ctx, file, user, google)


async def test_辨識器沒有重新檢查_使用者選待辦確認後_回應與資料庫一致(
    client: AsyncClient,
    session: AsyncSession,
    policy: Policy,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incident_id = await start(client, policy)
    state = await talk(client, incident_id)
    document = (await upload(client, incident_id, "a.pdf")).json()
    assert document["recognition_status"] == "needs_review"
    assert document["stored"] is True
    target = next(t for t in state["todos"] if t["document_code"] == "D02")
    monkeypatch.setattr(
        "app.api.routes.incidents.get_document_recognizer", lambda: _NoRecheck()
    )

    response = await client.post(
        f"/incidents/{incident_id}/documents/{document['id']}/recheck",
        json={"todo_id": target["id"]},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert (
        body["recognition_status"] == "recognized"
    )  # 已由使用者確認，不再是 needs_review
    assert body["todo_id"] == target["id"]
    assert body["todo_complete"] is True
    assert body["appended"] is False
    assert body["stored"] is True
    assert body["reason"] is None  # 不留「請選一項」的舊說明
    after = (await client.get(f"/incidents/{incident_id}")).json()
    ticked = next(t for t in after["todos"] if t["id"] == target["id"])
    assert ticked["is_done"] and ticked["done_by"] == "user"  # 使用者完成，不是 6 號
    row = (await session.exec(select(IncidentDocument))).one()
    await session.refresh(row)
    assert row.confirmed_by_user is True and str(row.incident_todo_id) == target["id"]
    assert row.storage_path.startswith("fake-cloud/")


async def test_辨識器沒有重新檢查_待辦已完成時回應是追加(
    client: AsyncClient, policy: Policy, monkeypatch: pytest.MonkeyPatch
) -> None:
    incident_id = await start(client, policy)
    state = await talk(client, incident_id)
    target = next(t for t in state["todos"] if t["document_code"] == "D02")
    first = (await upload(client, incident_id, "a.pdf")).json()
    second = (await upload(client, incident_id, "b.pdf")).json()
    monkeypatch.setattr(
        "app.api.routes.incidents.get_document_recognizer", lambda: _NoRecheck()
    )
    for doc in (first, second):
        response = await client.post(
            f"/incidents/{incident_id}/documents/{doc['id']}/recheck",
            json={"todo_id": target["id"]},
        )
        assert response.status_code == 200, response.text

    assert response.json()["appended"] is True  # 第二份對上時待辦已經完成
    assert response.json()["recognition_status"] == "recognized"


async def test_辨識器沒有重新檢查_文件沒有存放位置就不能確認_回應不會說有存(
    client: AsyncClient,
    session: AsyncSession,
    policy: Policy,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incident_id = await start(client, policy)
    state = await talk(client, incident_id)
    document = (await upload(client, incident_id, "a.pdf")).json()
    row = (await session.exec(select(IncidentDocument))).one()
    row.storage_path = ""
    session.add(row)
    await session.commit()
    monkeypatch.setattr(
        "app.api.routes.incidents.get_document_recognizer", lambda: _NoRecheck()
    )

    response = await client.post(
        f"/incidents/{incident_id}/documents/{document['id']}/recheck",
        json={"todo_id": state["todos"][0]["id"]},
    )

    assert response.status_code == 409
    await session.refresh(row)
    assert row.confirmed_by_user is False and row.recognition_status == "needs_review"
