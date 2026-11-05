"""待確認條文的逐條處理：放行、修改後放行、刪除（上傳 API 的接縫）。

工作直接建在資料庫（上傳流程怎麼產生待確認條文是另一張票），再用 API 逐條處理；
向量用測試的假供應商，不連網。
"""

import uuid

import pytest
from app.core.llm import embedding_model_name, get_embeddings
from app.ingest.catalog import InsuranceSpec, ParsedRule, import_catalog
from app.ingest.pending import PendingArticle
from app.models import IngestEvent, IngestJob, Insurance, InsuranceRule, RuleEmbedding
from httpx import AsyncClient
from sqlmodel import col, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

CODE = "FUBON07"


def rule(no: int, content: str = "") -> ParsedRule:
    return ParsedRule(
        insurance_code=CODE,
        article_no=no,
        chapter=f"條文{no}",
        title=f"標題{no}",
        content=content or f"第{no}條的內容",
        section=None,
        source_file="t.pdf",
        page_start=1,
        page_end=1,
    )


async def make_job(
    session: AsyncSession, nos: list[int], status: str = "needs_review"
) -> IngestJob:
    job = IngestJob(
        filename="t.pdf",
        insurance_code=CODE,
        insurance_name="旅遊不便險",
        status=status,
        pending_rules=[
            PendingArticle.from_rule(
                rule(n), [{"rule": "A2-content", "message": "內文與 PDF 不符"}]
            ).model_dump()
            for n in nos
        ],
    )
    session.add(job)
    await session.commit()
    return job


async def count(session: AsyncSession, model) -> int:
    return (await session.exec(select(func.count()).select_from(model))).one()


async def article_nos(session: AsyncSession) -> list[int]:
    rows = await session.exec(
        select(InsuranceRule.article_no).order_by(col(InsuranceRule.article_no))
    )
    return list(rows)


async def events(session: AsyncSession, job_id: uuid.UUID) -> list[IngestEvent]:
    return list(
        await session.exec(
            select(IngestEvent)
            .where(IngestEvent.job_id == job_id)
            .order_by(col(IngestEvent.seq))
        )
    )


def url(job: IngestJob, no: int, action: str) -> str:
    return f"/ingest/jobs/{job.id}/articles/{no}/{action}"


async def test_工作詳情列出待確認條文和原因(client: AsyncClient, session):
    job = await make_job(session, [1, 2])

    detail = (await client.get(f"/ingest/jobs/{job.id}")).json()

    assert detail["status"] == "needs_review"
    assert [(a["article_no"], a["status"]) for a in detail["articles"]] == [
        (1, "pending"),
        (2, "pending"),
    ]
    assert detail["articles"][0]["findings"][0]["rule"] == "A2-content"
    assert detail["articles"][0]["content"] == "第1條的內容"


async def test_放行一條只寫入這一條並算向量(client: AsyncClient, session):
    job = await make_job(session, [1, 2, 3])

    response = await client.post(url(job, 2, "release"))

    assert response.status_code == 200, response.text
    assert await article_nos(session) == [2]
    assert await count(session, RuleEmbedding) == 1
    detail = response.json()
    assert detail["status"] == "needs_review"
    assert {a["article_no"]: a["status"] for a in detail["articles"]} == {
        1: "pending",
        2: "released",
        3: "pending",
    }


async def test_放行不會刪掉險種已有的其他條文(client: AsyncClient, session):
    await import_catalog(
        session,
        [InsuranceSpec(code=CODE, name="旅遊不便險")],
        [rule(10), rule(11)],
        embeddings=get_embeddings(),
        model=embedding_model_name(),
    )
    job = await make_job(session, [1])

    assert (await client.post(url(job, 1, "release"))).status_code == 200

    assert await article_nos(session) == [1, 10, 11]


async def test_全部處理完工作結束並清空待確認條文(client: AsyncClient, session):
    job = await make_job(session, [1, 2])
    await client.post(url(job, 1, "release"))

    response = await client.post(url(job, 2, "delete"))

    detail = response.json()
    assert detail["status"] == "done"
    assert detail["articles"] == []
    summary = detail["summary"]
    assert {k: summary[k] for k in ("released", "deleted", "pending")} == {
        "released": 1,
        "deleted": 1,
        "pending": 0,
    }
    assert summary["selfcheck"]["checked"] == 1  # 放行的那一條也做了檢索自檢
    assert await article_nos(session) == [1]


async def test_刪除的條文不寫入也沒有向量(client: AsyncClient, session):
    job = await make_job(session, [1, 2])

    response = await client.post(url(job, 1, "delete"))

    assert response.status_code == 200
    assert await count(session, InsuranceRule) == 0
    assert await count(session, RuleEmbedding) == 0
    assert {a["article_no"]: a["status"] for a in response.json()["articles"]} == {
        1: "deleted",
        2: "pending",
    }


async def test_修改文字後放行_入庫的是新文字_舊字新字與原因記在事件(
    client: AsyncClient, session
):
    job = await make_job(session, [1, 2])

    response = await client.post(
        url(job, 1, "edit"),
        json={"content": "改過的內容", "reason": "實際保單是這樣寫"},
    )

    assert response.status_code == 200, response.text
    stored = (await session.exec(select(InsuranceRule))).one()
    assert stored.content == "改過的內容"
    assert await count(session, RuleEmbedding) == 1
    review = [e for e in await events(session, job.id) if e.step == "review"]
    assert len(review) == 1
    assert review[0].data and review[0].data["old_content"] == "第1條的內容"
    assert review[0].data["new_content"] == "改過的內容"
    assert review[0].data["reason"] == "實際保單是這樣寫"
    assert {a["article_no"]: a["edited"] for a in response.json()["articles"]}[1]


async def test_修改文字一定要有原因(client: AsyncClient, session):
    job = await make_job(session, [1])

    for body in ({"content": "新的"}, {"content": "新的", "reason": ""}):
        assert (await client.post(url(job, 1, "edit"), json=body)).status_code == 422
    assert await count(session, InsuranceRule) == 0


async def test_每個動作都留下事件紀錄且序號遞增(client: AsyncClient, session):
    job = await make_job(session, [1, 2])
    await client.post(url(job, 1, "release"))
    await client.post(url(job, 2, "delete"))

    seqs = [e.seq for e in await events(session, job.id)]
    assert seqs == [1, 2]
    steps = {e.step for e in await events(session, job.id)}
    assert steps == {"review"}


@pytest.mark.parametrize("action", ["release", "delete"])
async def test_處理過的條文不能再處理(client: AsyncClient, session, action):
    job = await make_job(session, [1, 2])
    await client.post(url(job, 1, "release"))

    assert (await client.post(url(job, 1, action))).status_code == 409


async def test_找不到的工作或條文回_404(client: AsyncClient, session):
    job = await make_job(session, [1])
    missing = uuid.uuid4()

    assert (
        await client.post(f"/ingest/jobs/{missing}/articles/1/release")
    ).status_code == 404
    assert (await client.post(url(job, 99, "release"))).status_code == 404


async def test_不是待確認的工作回_409(client: AsyncClient, session):
    job = await make_job(session, [1], status="done")

    assert (await client.post(url(job, 1, "release"))).status_code == 409


async def test_向量服務失敗時這一條維持待處理(
    client: AsyncClient, session, monkeypatch
):
    from app.api.routes import ingest as ingest_route

    class Broken:
        async def aembed_documents(self, texts):
            raise RuntimeError("向量服務連不上")

    monkeypatch.setattr(ingest_route, "get_embeddings", lambda: Broken())
    job = await make_job(session, [1])

    response = await client.post(url(job, 1, "release"))

    assert response.status_code == 502
    assert await count(session, InsuranceRule) == 0
    detail = (await client.get(f"/ingest/jobs/{job.id}")).json()
    assert detail["status"] == "needs_review"
    assert [a["status"] for a in detail["articles"]] == ["pending"]


async def test_全部放行_沿用原本的_approve_流程_舊格式也能讀(
    client: AsyncClient, session
):
    # 舊格式：只有條文欄位、沒有 status
    from dataclasses import asdict

    job = IngestJob(
        filename="t.pdf",
        insurance_code=CODE,
        insurance_name="旅遊不便險",
        status="needs_review",
        pending_rules=[asdict(rule(1)), asdict(rule(2))],
    )
    session.add(job)
    await session.commit()

    detail = (await client.get(f"/ingest/jobs/{job.id}")).json()
    assert [a["status"] for a in detail["articles"]] == ["pending", "pending"]
    assert await count(session, Insurance) == 0
