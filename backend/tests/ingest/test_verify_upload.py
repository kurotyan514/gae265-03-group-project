"""上傳單一險種時的逐條內容驗證：通過的入庫、其餘成為待確認條文（上傳 API 的接縫）。

用真實 PDF 與真實資料庫；「某幾條沒通過」靠切塊時動手腳製造（模擬切錯字），
向量與是否為條款的 LLM 在測試環境是假的。
"""

import dataclasses

import pytest
from app.api.routes import ingest as ingest_route
from app.core import db
from app.core.config import settings
from app.ingest import agent
from app.ingest.agent import Classification
from app.models import InsuranceRule, RuleEmbedding
from httpx import AsyncClient
from sqlmodel import col, func, select

from tests.ingest.test_agent import other_company_pdf

FORM = {"insurance_code": "FUBON07", "insurance_name": "旅遊不便險"}
BAD = (3, 5)  # 被動手腳的條號


pytestmark = pytest.mark.usefixtures("logged_in")


@pytest.fixture(autouse=True)
def use_test_engine(engine, monkeypatch):
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(ingest_route, "POLL_SECONDS", 0.05)

    async def yes(_: str) -> Classification:
        return Classification(is_policy=True, reason="有條文結構")

    monkeypatch.setattr(agent, "llm_classify", yes)


@pytest.fixture
def tamper(monkeypatch):
    """切塊時把 BAD 條文的字改掉，模擬切出來的內容與 PDF 不符。"""
    real = agent.split_single_product

    def split(pages, filename):
        chunks, notes = real(pages, filename)
        chunks = [
            dataclasses.replace(c, text="這段文字並不在原始文件裡")
            if c.kind == "article" and c.article_no in BAD
            else c
            for c in chunks
        ]
        return chunks, notes

    monkeypatch.setattr(agent, "split_single_product", split)


async def upload_and_wait(client: AsyncClient, pdf: bytes) -> dict:
    response = await client.post(
        "/ingest/jobs", files={"file": ("t.pdf", pdf, "application/pdf")}, data=FORM
    )
    job_id = response.json()["id"]
    await client.get(f"/ingest/jobs/{job_id}/events")  # 等處理完
    return (await client.get(f"/ingest/jobs/{job_id}")).json()


async def stored_nos(session) -> list[int]:
    rows = await session.exec(
        select(InsuranceRule.article_no).order_by(col(InsuranceRule.article_no))
    )
    return list(rows)


async def embeddings(session) -> int:
    return (await session.exec(select(func.count()).select_from(RuleEmbedding))).one()


def validate_events(detail: dict) -> list[dict]:
    return [
        e
        for e in detail["events"]
        if e["step"] == "validate" and e["status"] != "running"
    ]


@pytest.mark.usefixtures("tamper")
async def test_含錯誤條文時通過的入庫_沒通過的成為待確認且檢索不到(client, session):
    detail = await upload_and_wait(client, other_company_pdf("富邦產物"))

    assert detail["status"] == "needs_review"
    assert await stored_nos(session) == [1, 2, 4, 6]
    assert await embeddings(session) == 4
    assert {a["article_no"]: a["status"] for a in detail["articles"]} == {
        3: "pending",
        5: "pending",
    }
    assert detail["articles"][0]["findings"]  # 帶著沒通過的原因
    assert detail["summary"]["imported"] == 4
    assert detail["summary"]["pending"] == 2
    assert detail["events"][-1]["step"] == "done"
    assert detail["events"][-1]["status"] == "warning"


@pytest.mark.usefixtures("tamper")
async def test_兩次驗證與中間的修復都在事件紀錄裡_且不含條文內容(client):
    detail = await upload_and_wait(client, other_company_pdf("富邦產物"))

    checks = validate_events(detail)
    assert [e["data"]["pass"] for e in checks] == [1, 2]
    assert all(
        e["data"]["passed"] == 4 and e["data"]["not_passed"] == 2 for e in checks
    )
    assert all(e["data"]["rules"] for e in checks)  # 規則代碼摘要
    steps = [e["step"] for e in detail["events"]]
    first = steps.index("validate")
    assert "repair" in steps[first:]
    assert all("這段文字並不在原始文件裡" not in e["message"] for e in detail["events"])


@pytest.mark.usefixtures("tamper")
async def test_驗證次數設為_1_只驗一次且不修復再驗(client, monkeypatch):
    monkeypatch.setattr(settings, "INGEST_VERIFY_PASSES", 1)

    detail = await upload_and_wait(client, other_company_pdf("富邦產物"))

    assert len(validate_events(detail)) == 1
    assert all(e["step"] != "repair" for e in detail["events"])
    assert detail["status"] == "needs_review"


async def test_全部通過時只驗一次_險種以這次上傳為準(client, session):
    from app.core.llm import embedding_model_name, get_embeddings
    from app.ingest.catalog import InsuranceSpec, ParsedRule, import_catalog

    old = ParsedRule(
        insurance_code="FUBON07",
        article_no=40,
        chapter="條文40",
        title="舊條文",
        content="舊版才有的條文",
        section=None,
        source_file="old.pdf",
        page_start=1,
        page_end=1,
    )
    await import_catalog(
        session,
        [InsuranceSpec(code="FUBON07", name="旅遊不便險")],
        [old],
        embeddings=get_embeddings(),
        model=embedding_model_name(),
    )

    detail = await upload_and_wait(client, other_company_pdf("富邦產物"))

    assert detail["status"] == "done"
    assert len(validate_events(detail)) == 1
    assert await stored_nos(session) == [1, 2, 3, 4, 5, 6]  # 舊的 40 被 prune


@pytest.mark.usefixtures("tamper")
async def test_部分入庫時不刪險種裡舊版的條文(client, session):
    from app.core.llm import embedding_model_name, get_embeddings
    from app.ingest.catalog import InsuranceSpec, ParsedRule, import_catalog

    old = ParsedRule(
        insurance_code="FUBON07",
        article_no=40,
        chapter="條文40",
        title="舊條文",
        content="舊版才有的條文",
        section=None,
        source_file="old.pdf",
        page_start=1,
        page_end=1,
    )
    await import_catalog(
        session,
        [InsuranceSpec(code="FUBON07", name="旅遊不便險")],
        [old],
        embeddings=get_embeddings(),
        model=embedding_model_name(),
    )

    await upload_and_wait(client, other_company_pdf("富邦產物"))

    assert await stored_nos(session) == [1, 2, 4, 6, 40]  # 已知取捨：舊條文殘留


async def test_PDF_讀不出來時不入庫任何條文_全部待確認(client, session, monkeypatch):

    def broken(*_args, **_kwargs):
        raise RuntimeError("壞掉的 PDF")

    monkeypatch.setattr("app.ingest.verify.build_baseline", broken)

    detail = await upload_and_wait(client, other_company_pdf("富邦產物"))

    assert detail["status"] == "needs_review"
    assert await stored_nos(session) == []
    assert await embeddings(session) == 0
    assert len(detail["articles"]) == 6
    checks = validate_events(detail)
    assert len(checks) == 1  # 讀不出來不重試
    assert checks[0]["status"] == "error"
    assert checks[0]["data"]["unreadable"] is True
    assert detail["events"][-1]["status"] == "warning"


@pytest.mark.usefixtures("tamper")
async def test_逐條放行_修改_刪除後入庫結果符合預期(client, session):
    detail = await upload_and_wait(client, other_company_pdf("富邦產物"))
    job_id = detail["id"]

    release = await client.post(f"/ingest/jobs/{job_id}/articles/3/release")
    assert release.status_code == 200, release.text
    assert await stored_nos(session) == [1, 2, 3, 4, 6]

    edit = await client.post(
        f"/ingest/jobs/{job_id}/articles/5/edit",
        json={"content": "人工修正後的第五條內容", "reason": "對照原文修正"},
    )
    assert edit.status_code == 200, edit.text
    assert edit.json()["status"] == "done"
    assert await stored_nos(session) == [1, 2, 3, 4, 5, 6]
    assert await embeddings(session) == 6


@pytest.mark.usefixtures("tamper")
async def test_待確認條文刪除後沒有入庫也沒有向量(client, session):
    detail = await upload_and_wait(client, other_company_pdf("富邦產物"))
    job_id = detail["id"]

    await client.post(f"/ingest/jobs/{job_id}/articles/3/delete")
    final = await client.post(f"/ingest/jobs/{job_id}/articles/5/delete")

    assert final.json()["status"] == "done"
    assert await stored_nos(session) == [1, 2, 4, 6]
    assert await embeddings(session) == 4


@pytest.fixture
def seen_company(monkeypatch):
    """抓 agent.verify_articles 收到的 spec.company。"""
    seen: list[str | None] = []
    real = agent.verify_articles

    def spy(path, inputs, spec, **kwargs):
        seen.append(spec.company)
        return real(path, inputs, spec, **kwargs)

    monkeypatch.setattr(agent, "verify_articles", spy)
    return seen


async def test_不填_company_時由險種代碼前綴推斷(client, seen_company):
    await upload_and_wait(client, other_company_pdf("富邦產物"))

    assert seen_company and set(seen_company) == {"富邦產物"}  # FUBON07


async def test_有填_company_時以填的為準(client, seen_company):
    response = await client.post(
        "/ingest/jobs",
        files={"file": ("t.pdf", other_company_pdf("富邦產物"), "application/pdf")},
        data={**FORM, "company": "華南產物"},
    )
    await client.get(f"/ingest/jobs/{response.json()['id']}/events")

    assert seen_company and set(seen_company) == {"華南產物"}
