import pymupdf
from app.core.config import settings
from app.core.llm import embedding_model_name, get_embeddings
from app.ingest.agent import Classification, fail_stale_jobs, run_ingest_job
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
    engine: AsyncEngine, pdf: bytes, classifier
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
    )
    async with AsyncSession(engine, expire_on_commit=False) as session:
        job = (await session.exec(select(IngestJob))).one()
        events = (
            await session.exec(select(IngestEvent).order_by(col(IngestEvent.seq)))
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


async def test_規則判斷不是條款就停下且不呼叫_LLM(engine, session):
    called = False

    async def spy(sample: str) -> Classification:
        nonlocal called
        called = True
        return await yes(sample)

    job, events = await run(engine, blank_pdf("今天天氣很好"), spy)

    assert job.status == "rejected"
    assert not called
    assert events[-1].step == "done" and events[-1].status == "error"
    assert await count(session, InsuranceRule) == 0


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
