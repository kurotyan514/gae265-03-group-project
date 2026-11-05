"""7 號 agent 的 build：從事件資料整理送件包（規格：docs/specs/agent-7-package.md）。

直接呼叫 build，自己組事件資料，不連資料庫、不連 Google。
"""

import json
import uuid
from datetime import date
from pathlib import Path

import pytest
from app.agents.package import GmailClaimPackager, packager
from app.contracts import (
    DocumentView,
    FactView,
    IncidentContext,
    PolicySummary,
    TodoView,
)


def _policy(
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    sum_insured: int | None = None,
    plan_id: str = "fubon_advanced",
) -> PolicySummary:
    return PolicySummary(
        plan_id=plan_id,
        plan_name="富邦國外旅平險-進階型",
        sum_insured=sum_insured,
        start_date=start_date,
        end_date=end_date,
        insurance_codes=[],
        coverages=[],
    )


def _document(
    status: str,
    *,
    storage_path: str = "drive-file-id",
    confirmed: bool = False,
    todo: TodoView | None = None,
) -> DocumentView:
    return DocumentView(
        id=uuid.uuid4(),
        todo_id=todo.id if todo else None,
        file_name=f"行李遺失或損壞_{status}_1.pdf",
        content_type="application/pdf",
        storage_path=storage_path,
        recognition_status=status,  # pyright: ignore[reportArgumentType]
        confirmed_by_user=confirmed,
    )


def _todo(
    status: str,
    *,
    done_by: str | None = None,
    without_document: bool = False,
    scope: str = "incident",
    title: str | None = None,
    sort_order: int = 0,
) -> TodoView:
    return TodoView(
        id=uuid.uuid4(),
        phase="after_return",
        title=title or f"待辦_{status}",
        scope=scope,  # pyright: ignore[reportArgumentType]
        sort_order=sort_order,
        is_done=status == "done",
        status=status,  # pyright: ignore[reportArgumentType]
        done_by=done_by,  # pyright: ignore[reportArgumentType]
        without_document=without_document,
    )


def _incident(
    documents: list[DocumentView] | None = None,
    todos: list[TodoView] | None = None,
    policy: PolicySummary | None = None,
    *,
    description: str = "託運行李遺失",
    destination: str | None = None,
    incident_type_name: str | None = None,
    facts: list[FactView] | None = None,
) -> IncidentContext:
    return IncidentContext(
        incident_id=uuid.uuid4(),
        title="行李遺失",
        description=description,
        destination=destination,
        incident_type_name=incident_type_name,
        facts=facts or [],
        status="open",
        policy=policy or _policy(),
        documents=documents or [],
        todos=todos or [],
    )


async def test_附件只取辨識通過或使用者確認過的文件() -> None:
    todo = _todo("done")
    recognized = _document("recognized", todo=todo)
    confirmed = _document("needs_review", confirmed=True, todo=todo)
    unconfirmed = _document("needs_review", todo=todo)
    incomplete = _document("incomplete", storage_path="", todo=todo)
    failed = _document("failed", storage_path="", todo=todo)
    ctx = _incident(
        [recognized, confirmed, unconfirmed, incomplete, failed], todos=[todo]
    )

    package = await GmailClaimPackager().build(ctx)

    assert {a.document_id for a in package.attachments} == {
        recognized.id,
        confirmed.id,
    }


async def test_缺漏待辦只算還沒做的_不適用與未附文件都不算() -> None:
    pending = _todo("pending")
    done_by_agent = _todo("done", done_by="agent")
    without_document = _todo("done", done_by="user", without_document=True)
    not_applicable = _todo("not_applicable")
    ctx = _incident(todos=[pending, done_by_agent, without_document, not_applicable])

    package = await GmailClaimPackager().build(ctx)

    assert package.missing_todo_ids == [pending.id]


async def test_主旨是方案名稱加保險期間() -> None:
    ctx = _incident(
        policy=_policy(start_date=date(2026, 8, 10), end_date=date(2026, 8, 14))
    )

    package = await GmailClaimPackager().build(ctx)

    # 依 7 號提供的範本，主旨只放方案名稱（2026-11-05 決定）
    assert (
        package.subject == "旅遊保險理賠申請－富邦國外旅平險-進階型－2026/08/10～08/14"
    )


async def test_抓不到保險期間時主旨留請填寫保險期間() -> None:
    ctx = _incident(policy=_policy(start_date=None, end_date=None))

    package = await GmailClaimPackager().build(ctx)

    # 主旨要寫明是哪一項沒抓到；內文的保險期間仍是「（請填寫）」（2026-11-05 7 號決定）
    assert (
        package.subject == "旅遊保險理賠申請－富邦國外旅平險-進階型－（請填寫保險期間）"
    )


async def test_保險期間跨年時迄日加上年份() -> None:
    ctx = _incident(
        policy=_policy(start_date=date(2026, 12, 30), end_date=date(2027, 1, 3))
    )

    package = await GmailClaimPackager().build(ctx)

    # 跨年時迄日加上年份（2026-11-05 7 號決定）
    assert (
        package.subject
        == "旅遊保險理賠申請－富邦國外旅平險-進階型－2026/12/30～2027/01/03"
    )


async def test_沒有存檔位置的文件不當附件() -> None:
    # 平台目前不會給這種資料；7 號寄信時要靠 storage_path 向 Drive 取檔，先擋下來
    todo = _todo("done")
    normal = _document("recognized", todo=todo)
    recognized_without_file = _document("recognized", storage_path="", todo=todo)
    confirmed_without_file = _document(
        "needs_review", storage_path="", confirmed=True, todo=todo
    )
    ctx = _incident(
        [normal, recognized_without_file, confirmed_without_file], todos=[todo]
    )

    package = await GmailClaimPackager().build(ctx)

    assert [a.document_id for a in package.attachments] == [normal.id]


async def test_理賠申請書D10的文件排在附件最後() -> None:
    # 依 7 號提供的範本，附件清單的最後一項是理賠申請書
    # 平台建 D10 時沿用範本的順序號，可能比事件待辦小
    claim_form = _todo("done", scope="policy", title="理賠申請書", sort_order=0)
    pir = _todo("done", title="航空公司申請行李事故報告（PIR）", sort_order=1)
    claim_form_doc = _document("recognized", todo=claim_form)  # 比較早上傳
    pir_doc = _document("recognized", todo=pir)
    ctx = _incident([claim_form_doc, pir_doc], todos=[claim_form, pir])

    package = await GmailClaimPackager().build(ctx)

    assert [a.document_id for a in package.attachments] == [
        pir_doc.id,
        claim_form_doc.id,
    ]


async def test_對不到待辦的文件不當附件() -> None:
    # 只寄待辦清單要求的文件；使用者多傳、6 號對不到待辦的不寄（2026-11-05 7 號決定）
    delay_proof = _todo("done", title="航空業者出具的延誤證明")
    requested = _document("recognized", todo=delay_proof)
    extra = _document("recognized")  # 例如延誤期間的飯店收據，todo_id 是空的
    ctx = _incident([requested, extra], todos=[delay_proof])

    package = await GmailClaimPackager().build(ctx)

    assert [a.document_id for a in package.attachments] == [requested.id]


async def test_附件依待辦順序排_不是上傳順序() -> None:
    delay_proof = _todo("done", title="航空業者出具的延誤證明", sort_order=0)
    boarding_pass = _todo("done", title="機票及登機證", sort_order=1)
    boarding_pass_doc = _document("recognized", todo=boarding_pass)  # 先上傳
    delay_proof_doc = _document("recognized", todo=delay_proof)
    ctx = _incident(
        [boarding_pass_doc, delay_proof_doc], todos=[delay_proof, boarding_pass]
    )

    package = await GmailClaimPackager().build(ctx)

    assert [a.document_id for a in package.attachments] == [
        delay_proof_doc.id,
        boarding_pass_doc.id,
    ]


async def test_內文的保單資訊() -> None:
    ctx = _incident(
        policy=_policy(
            start_date=date(2026, 8, 10),
            end_date=date(2026, 8, 14),
            sum_insured=6_000_000,
        )
    )

    package = await GmailClaimPackager().build(ctx)

    # 依 7 號提供的範本；公司由 plan_id 查方案資料（fubon_advanced 是富邦產物）
    assert (
        "保單資訊\n"
        "・公司：富邦產物\n"
        "・方案：富邦國外旅平險-進階型\n"
        "・保額：600 萬\n"
        "・保險期間：2026/08/10～08/14\n"
        "・保單號碼：（請填寫）"
    ) in package.body


async def test_保額不是萬的整數倍時不捨去() -> None:
    # ADR-0004：數字由程式產生，不內插、不四捨五入
    ctx = _incident(policy=_policy(sum_insured=6_500_123))

    package = await GmailClaimPackager().build(ctx)

    assert "6,500,123" in package.body


async def test_守門_每個方案都查得到保險公司() -> None:
    # 7 號自己讀 plans.json 取公司名稱（2026-11-05 決定）。檔案搬家或格式改了，這裡會失敗，
    # 讓改的人在 CI 就知道 7 號會受影響。
    plans_file = Path(__file__).resolve().parents[3] / "data" / "config" / "plans.json"
    plans = json.loads(plans_file.read_text(encoding="utf-8"))["plans"]
    assert plans

    for plan in plans:
        ctx = _incident(policy=_policy(plan_id=plan["id"]))
        package = await GmailClaimPackager().build(ctx)
        assert plan["company"] and f"・公司：{plan['company']}\n" in package.body, plan[
            "id"
        ]


async def test_方案資料查不到時公司留請填寫() -> None:
    ctx = _incident(policy=_policy(plan_id="not_in_plans_json"))

    package = await GmailClaimPackager().build(ctx)

    assert "・公司：（請填寫）\n" in package.body


async def test_方案資料檔不存在時公司留請填寫_其他照常(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # 使用者不該因為公司名稱查不到而看不到送件包（2026-11-05 7 號決定）
    monkeypatch.setattr(packager, "PLANS_FILE", tmp_path / "不存在.json")
    ctx = _incident(policy=_policy(sum_insured=6_000_000))

    package = await GmailClaimPackager().build(ctx)

    assert "・公司：（請填寫）\n" in package.body
    assert "・保額：600 萬\n" in package.body


async def test_方案資料檔格式不對時公司留請填寫(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    broken = tmp_path / "plans.json"
    broken.write_text('{"items": []}', encoding="utf-8")  # 例如 plans 改了名字
    monkeypatch.setattr(packager, "PLANS_FILE", broken)

    package = await GmailClaimPackager().build(_incident())

    assert "・公司：（請填寫）\n" in package.body


async def test_保額一千萬寫成1000萬_不加逗號() -> None:
    # 2026-11-05 7 號決定
    ctx = _incident(policy=_policy(sum_insured=10_000_000))

    package = await GmailClaimPackager().build(ctx)

    assert "・保額：1000 萬\n" in package.body


async def test_保額不是萬的整數倍時寫完整金額加元() -> None:
    # 2026-11-05 7 號決定：維持「6,500,123 元」
    ctx = _incident(policy=_policy(sum_insured=6_500_123))

    package = await GmailClaimPackager().build(ctx)

    assert "・保額：6,500,123 元\n" in package.body


def _occurred_on(value: str) -> FactView:
    """5 號記下的發生日期：代號是事故設定檔共用欄位的 date。"""
    return FactView(fact_key="date", label="發生日期", value=value)


async def test_內文的事故摘要() -> None:
    ctx = _incident(
        incident_type_name="班機延誤",
        facts=[_occurred_on("2026/8/10")],  # 5 號可能存成月份一位數
        destination="日本",
        description="我從新加坡搭長榮回台北，到桃園領行李時才發現託運的行李箱不見了",
    )

    package = await GmailClaimPackager().build(ctx)

    # 格式依 7 號決定：各項分開、不組句子，使用者原話照原樣放、不加字（2026-11-06）
    lines = package.body.splitlines()
    assert lines[lines.index("事故摘要") + 1] == (
        "・班機延誤 · 2026/08/10 · 日本："
        "我從新加坡搭長榮回台北，到桃園領行李時才發現託運的行李箱不見了"
    )


async def test_事故摘要抓不到的項目寫明要填什麼() -> None:
    ctx = _incident(
        incident_type_name=None, facts=[], destination=None, description="  "
    )

    package = await GmailClaimPackager().build(ctx)

    # 2026-11-06 7 號決定：事故摘要每一項抓不到時寫明是哪一項
    assert (
        "事故摘要\n"
        "・（請填寫事故類型） · （請填寫日期） · （請填寫地點）：（請填寫經過）"
    ) in package.body


async def test_發生日期看不懂時照抄原文() -> None:
    # 5 號問不到時存「不知道」；5 號只檢查格式，可能放行不存在的日期
    for raw in ["不知道", "2026/13/45"]:
        ctx = _incident(incident_type_name="班機延誤", facts=[_occurred_on(raw)])

        package = await GmailClaimPackager().build(ctx)

        assert f"・班機延誤 · {raw} · " in package.body, raw
