"""LLM 確認「工具不確定」的條文（上傳 API 的接縫）。

兩套 PDF 工具讀法不同的情況很難用真實 PDF 重現，所以把第 3 條的驗證結論換成「工具不確定」，
第 5 條維持真實的「確定錯誤」；LLM 與向量都是假的。
"""

import pytest
from app.api.routes import ingest as ingest_route
from app.core import db
from app.core.config import settings
from app.ingest import agent
from app.ingest.agent import Classification
from app.ingest.confirm import Confirmation, ConfirmRequest
from app.ingest.verify import ArticleVerdict, Finding, Status
from app.models import InsuranceRule
from sqlmodel import col, select

from tests.ingest.test_agent import other_company_pdf
from tests.ingest.test_verify_upload import (  # noqa: F401
    stored_nos,
    tamper,
    upload_and_wait,
)

UNSURE = 3  # 換成「工具不確定」的條號
WRONG = 5  # 維持「確定錯誤」的條號
TAMPERED_TEXT = "這段文字並不在原始文件裡"


pytestmark = pytest.mark.usefixtures("logged_in")


@pytest.fixture(autouse=True)
def setup(engine, monkeypatch):
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(ingest_route, "POLL_SECONDS", 0.05)

    async def yes(_: str) -> Classification:
        return Classification(is_policy=True, reason="有條文結構")

    monkeypatch.setattr(agent, "llm_classify", yes)

    real = agent._verify_pdf

    def unsure_for_article_3(*args, **kwargs):
        result = real(*args, **kwargs)
        if result is None:
            return None
        return [
            ArticleVerdict(
                article_no=v.article_no,
                status=Status.WARNING,
                findings=[
                    Finding(
                        check="accuracy",
                        rule="A3-disputed-match",
                        status=Status.WARNING,
                        severity="中",
                        message="兩套工具讀出的內文不同",
                        article_no=v.article_no,
                        evidence={"pymupdf": "甲讀法", "pdfplumber": "乙讀法"},
                    )
                ],
            )
            if v.article_no == UNSURE
            else v
            for v in result
        ]

    monkeypatch.setattr(agent, "_verify_pdf", unsure_for_article_3)


class Recorder:
    def __init__(self, ok: bool = True, reason: str = "只是排版差異") -> None:
        self.ok, self.reason = ok, reason
        self.requests: list[ConfirmRequest] = []

    async def __call__(self, request: ConfirmRequest) -> Confirmation:
        self.requests.append(request)
        return Confirmation(ok=self.ok, reason=self.reason)


def install(monkeypatch, confirmer) -> None:
    monkeypatch.setattr(agent, "llm_confirm", confirmer)


def confirm_events(detail: dict) -> list[dict]:
    return [e for e in detail["events"] if (e["data"] or {}).get("llm_confirm")]


@pytest.mark.usefixtures("tamper")
async def test_LLM_說可以時工具不確定的條文入庫_確定錯誤的仍待確認(
    client, session, monkeypatch
):
    llm = Recorder(ok=True)
    install(monkeypatch, llm)

    detail = await upload_and_wait(client, other_company_pdf("富邦產物"))

    assert UNSURE in await stored_nos(session)
    assert [a["article_no"] for a in detail["articles"]] == [WRONG]
    # 確定錯誤的條文根本不會送給 LLM，所以它說什麼都放行不了
    assert [r.article_no for r in llm.requests] == [UNSURE]


@pytest.mark.usefixtures("tamper")
async def test_LLM_看得到兩套工具的讀法(client, monkeypatch):
    llm = Recorder()
    install(monkeypatch, llm)

    await upload_and_wait(client, other_company_pdf("富邦產物"))

    evidence = llm.requests[0].findings[0].evidence
    assert evidence == {"pymupdf": "甲讀法", "pdfplumber": "乙讀法"}


@pytest.mark.usefixtures("tamper")
async def test_LLM_放行不會改變入庫的文字(client, session, monkeypatch):
    install(monkeypatch, Recorder(ok=True))

    await upload_and_wait(client, other_company_pdf("富邦產物"))

    rule = (
        await session.exec(
            select(InsuranceRule).where(col(InsuranceRule.article_no) == UNSURE)
        )
    ).one()
    assert rule.content == TAMPERED_TEXT  # 切塊的結果原樣入庫


@pytest.mark.usefixtures("tamper")
async def test_LLM_說不行時進待確認_理由出現在原因裡(client, session, monkeypatch):
    install(monkeypatch, Recorder(ok=False, reason="第二款的金額不同"))

    detail = await upload_and_wait(client, other_company_pdf("富邦產物"))

    assert UNSURE not in await stored_nos(session)
    article = next(a for a in detail["articles"] if a["article_no"] == UNSURE)
    reasons = [f["message"] for f in article["findings"]]
    assert any("第二款的金額不同" in m for m in reasons)
    assert any(f["rule"] == "A3-disputed-match" for f in article["findings"])


@pytest.mark.usefixtures("tamper")
async def test_事件記錄理由_供應商與模型(client, monkeypatch):
    install(monkeypatch, Recorder(ok=True, reason="只是排版差異"))

    detail = await upload_and_wait(client, other_company_pdf("富邦產物"))

    (event,) = confirm_events(detail)
    data = event["data"]
    assert data["provider"] == settings.LLM_PROVIDER
    assert "model" in data
    assert data["llm_confirm"] == [
        {
            "article_no": UNSURE,
            "ok": True,
            "reason": "只是排版差異",
            "rules": ["A3-disputed-match"],
        }
    ]


@pytest.mark.usefixtures("tamper")
async def test_確認次數設為_0_不問_LLM(client, session, monkeypatch):
    monkeypatch.setattr(settings, "INGEST_VERIFY_LLM_PASSES", 0)
    llm = Recorder(ok=True)
    install(monkeypatch, llm)

    detail = await upload_and_wait(client, other_company_pdf("富邦產物"))

    assert llm.requests == []
    assert UNSURE not in await stored_nos(session)
    assert {a["article_no"] for a in detail["articles"]} == {UNSURE, WRONG}


@pytest.mark.usefixtures("tamper")
async def test_確認次數大於_1_時第一次不行會再問(client, session, monkeypatch):
    monkeypatch.setattr(settings, "INGEST_VERIFY_LLM_PASSES", 2)
    answers = iter([False, True])

    async def flaky(_: ConfirmRequest) -> Confirmation:
        return Confirmation(ok=next(answers), reason="第二次看懂了")

    install(monkeypatch, flaky)

    await upload_and_wait(client, other_company_pdf("富邦產物"))

    assert UNSURE in await stored_nos(session)


@pytest.mark.usefixtures("tamper")
async def test_LLM_呼叫失敗時工作不失敗_這一條維持待確認(client, session, monkeypatch):
    async def broken(_: ConfirmRequest) -> Confirmation:
        raise RuntimeError("連不上")

    install(monkeypatch, broken)

    detail = await upload_and_wait(client, other_company_pdf("富邦產物"))

    assert detail["status"] == "needs_review"
    assert UNSURE not in await stored_nos(session)
    article = next(a for a in detail["articles"] if a["article_no"] == UNSURE)
    assert any("連不上" in f["message"] for f in article["findings"])
