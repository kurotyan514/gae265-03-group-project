"""契約 v2（提案 docs/agents/handoff/contract-v2-proposal.md）：平台端的行為。

走上傳與對話的 API；agent 用假實作，必要時換成回傳指定結果的版本。
"""

import uuid
from datetime import date
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


def test_契約版本是_2_5_0() -> None:
    assert CONTRACT_VERSION == "2.5.0"
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
    assert scopes == {"D01": "incident", "D02": "incident", "D10": "policy"}
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


async def test_理賠申請書同一張保單只建一次(
    client: AsyncClient, session: AsyncSession, policy: Policy
) -> None:
    await talk(client, await start(client, policy))
    await talk(client, await start(client, policy))

    forms = (
        await session.exec(
            select(IncidentTodo).where(IncidentTodo.policy_id == policy.id)
        )
    ).all()
    assert [t.document_code for t in forms] == ["D10"]


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
