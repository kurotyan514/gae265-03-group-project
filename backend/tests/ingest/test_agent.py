import pymupdf
from app.core.config import settings
from app.core.llm import embedding_model_name, get_embeddings
from app.ingest.agent import (
    Classification,
    fail_stale_jobs,
    resume_ingest_job,
    run_ingest_job,
)
from app.ingest.clauses import Chunk
from app.ingest.validate import repair_articles
from app.models import IngestEvent, IngestJob, InsuranceRule, RuleEmbedding
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

CLAUSE_PDF = settings.DATA_DIR / "clauses" / "T113.pdf"


async def yes(_: str) -> Classification:
    return Classification(
        is_policy=True, reason="有條文結構", insurance_name="旅遊不便險"
    )


async def no(_: str) -> Classification:
    return Classification(is_policy=False, reason="是廣告文宣")


def blank_pdf(text: str) -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), text)
    return doc.tobytes()


async def run(
    engine: AsyncEngine, pdf: bytes, classifier, **kwargs
) -> tuple[IngestJob, list[IngestEvent]]:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        job = IngestJob(
            filename="x.pdf", insurance_code="T113", insurance_name="旅遊不便險"
        )
        session.add(job)
        await session.commit()
    await run_ingest_job(
        engine,
        job.id,
        pdf,
        embeddings=get_embeddings(),
        model=embedding_model_name(),
        classifier=classifier,
        **kwargs,
    )
    async with AsyncSession(engine, expire_on_commit=False) as session:
        job = (
            await session.exec(select(IngestJob).where(IngestJob.id == job.id))
        ).one()
        events = (
            await session.exec(
                select(IngestEvent)
                .where(IngestEvent.job_id == job.id)
                .order_by(col(IngestEvent.seq))
            )
        ).all()
    return job, list(events)


async def count(session: AsyncSession, table) -> int:
    return (await session.scalar(select(func.count()).select_from(table))) or 0


async def test_真實條款走完全部步驟並入庫(engine, session):
    job, events = await run(engine, CLAUSE_PDF.read_bytes(), yes)

    assert job.status == "done"
    steps = [e.step for e in events if e.status != "running"]
    assert steps == [
        "extract",
        "classify",
        "chunk",
        "validate",
        "embed",
        "import",
        "done",
    ]
    assert [e.seq for e in events] == list(range(1, len(events) + 1))
    assert job.summary and job.summary["rules"] == job.summary["embeddings"] > 0
    assert await count(session, InsuranceRule) == job.summary["rules"]
    assert await count(session, RuleEmbedding) == job.summary["embeddings"]


async def test_embedding_有逐批進度(engine):
    _, events = await run(engine, CLAUSE_PDF.read_bytes(), yes)

    embed = [e for e in events if e.step == "embed" and e.current is not None]
    assert embed[0].current == 0
    assert embed[-1].current == embed[-1].total


async def test_沒有任何條文結構時由_LLM_決定是否拒絕(engine, session):
    job, events = await run(engine, blank_pdf("今天天氣很好"), no)

    assert job.status == "rejected"
    assert events[-1].step == "done" and events[-1].status == "error"
    assert await count(session, InsuranceRule) == 0


async def test_LLM_認為是條款但切不出條文_標成_failed(engine, session):
    job, events = await run(engine, blank_pdf("今天天氣很好"), yes)

    assert job.status == "failed"
    assert any(e.step == "chunk" and e.status == "error" for e in events)
    assert await count(session, InsuranceRule) == 0


async def test_掃描檔沒有文字層_標成_failed而不是拒絕(engine):
    doc = pymupdf.open()
    doc.new_page()

    job, events = await run(engine, doc.tobytes(), yes)

    assert job.status == "failed"
    assert "OCR" in events[1].message


async def test_LLM_判斷不是條款就不入庫(engine, session):
    job, events = await run(engine, CLAUSE_PDF.read_bytes(), no)

    assert job.status == "rejected"
    assert any("廣告" in e.message for e in events if e.step == "classify")
    assert all(e.step not in {"embed", "import"} for e in events)
    assert await count(session, InsuranceRule) == 0


async def test_壞掉的_PDF_標成_failed(engine):
    job, events = await run(engine, b"%PDF-1.4 not really", yes)

    assert job.status == "failed"
    assert events[-1].step == "done" and events[-1].status == "error"


async def test_重啟時把殘留的_running_標成_failed(engine, session):
    job = IngestJob(
        filename="x.pdf", insurance_code="T113", insurance_name="旅遊不便險"
    )
    session.add(job)
    await session.commit()

    assert await fail_stale_jobs(engine) == 1

    await session.refresh(job)
    assert job.status == "failed"
    assert await fail_stale_jobs(engine) == 0


def other_company_pdf(company: str) -> bytes:
    """標題行以 company 開頭、有 6 條條文的最小 PDF（要 CJK 字型，否則文字會變成點）。"""
    articles = "\n".join(
        f"第{n}條 條文{n}\n本保險契約的第{n}條內容。" for n in "一二三四五六"
    )
    doc = pymupdf.open()
    doc.new_page().insert_text(
        (72, 72),
        f"{company}測試旅行保險\n第一章 共同條款\n{articles}",
        fontname="china-t",
    )
    return doc.tobytes()


async def test_非富邦的公司不指定公司名稱時退回用第一行當標題並入庫(engine, session):
    job, events = await run(engine, other_company_pdf("國泰產物"), yes)

    assert job.status == "done"
    repair = [e for e in events if e.step == "repair" and e.status != "running"]
    assert repair and "改用第一行" in repair[0].data["actions"][0]  # pyright: ignore[reportOptionalSubscript]
    assert await count(session, InsuranceRule) == 6


async def test_指定公司名稱時不需要修復(engine, session):
    job, events = await run(
        engine, other_company_pdf("國泰產物"), yes, company="國泰產物"
    )

    assert job.status == "done"
    assert all(e.step != "repair" for e in events)
    assert await count(session, InsuranceRule) == 6


def few_articles_pdf() -> bytes:
    """只有 3 條，少於 INGEST_MIN_ARTICLES：驗證不過，但仍是條款。"""
    doc = pymupdf.open()
    doc.new_page().insert_text(
        (72, 72),
        "富邦產物測試旅行保險\n第一條 甲\n內容一。\n第二條 乙\n內容二。\n第三條 丙\n內容三。",
        fontname="china-t",
    )
    return doc.tobytes()


async def test_驗證不過的條款進_needs_review且不寫入正式表(engine, session):
    job, events = await run(engine, few_articles_pdf(), yes)

    assert job.status == "needs_review"
    assert job.pending_rules and len(job.pending_rules) == 3
    assert events[-1].step == "done" and events[-1].status == "warning"
    assert any(e.step == "validate" and e.status == "error" for e in events)
    assert await count(session, InsuranceRule) == 0


async def test_人工確認後仍然寫入並接續事件序號(engine, session):
    job, before = await run(engine, few_articles_pdf(), yes)

    await resume_ingest_job(
        engine, job.id, embeddings=get_embeddings(), model=embedding_model_name()
    )

    async with AsyncSession(engine, expire_on_commit=False) as s:
        job = (await s.exec(select(IngestJob).where(IngestJob.id == job.id))).one()
        events = (
            await s.exec(
                select(IngestEvent)
                .where(IngestEvent.job_id == job.id)
                .order_by(col(IngestEvent.seq))
            )
        ).all()
    assert job.status == "done" and job.pending_rules is None
    assert [e.seq for e in events] == list(range(1, len(events) + 1))
    assert len(events) > len(before)
    assert await count(session, InsuranceRule) == 3
    assert await count(session, RuleEmbedding) == 3


def chunk(no: int, text: str = "內容", title: str = "標題") -> Chunk:
    return Chunk(
        id=f"x|y|{no}", kind="article", company="x", product="y", chapter="",
        article_no=no, article_title=title, text=text, source_file="x.pdf",
        page_start=1, page_end=1,
    )  # fmt: skip


def test_repair_排除空內容與超出範圍的條號_重複只留較長的():
    fixed, actions = repair_articles(
        [
            chunk(1),
            chunk(2, text="  "),
            chunk(150),
            chunk(3, "短"),
            chunk(3, "比較長的內容"),
        ]
    )

    assert [c.article_no for c in fixed] == [1, 3]
    assert fixed[1].text == "比較長的內容"
    assert len(actions) == 3


def test_repair_不改動條文文字():
    original = chunk(1, "第一條的原文\n不可被改寫")
    fixed, actions = repair_articles([original])

    assert fixed == [original] and actions == []
