"""已確認的合訂本拆分清單 → 逐險種入庫（票 #96）。

每個收錄的險種各建一個上傳工作（`ingest_job`），沿用單一險種上傳的整套流程：
內容驗證 → LLM 確認 → 通過的入庫、其餘成為待確認條文 → 檢索自檢，事件串流與待確認條文的處理都共用。
差別在於：清單已經由管理者確認過是條款，不需要判斷；驗證範圍用清單的標題行限定到行層級，
鄰近險種的文字不會被算進標準答案。
"""

import logging
from typing import Any

from langchain_core.embeddings import Embeddings
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.ingest.agent import Emitter, _finish, _guarded, _process
from app.ingest.bundle import Section, SourceSpec, split_bundle
from app.ingest.bundle_split import (
    _pages,
    split_pdf,
    split_to_source,
)
from app.ingest.confirm import Confirmer
from app.ingest.verify import SectionRange
from app.models import BundleSplit, IngestEvent, IngestJob, Insurance

logger = logging.getLogger(__name__)


async def create_jobs(session: AsyncSession, split: BundleSplit) -> list[IngestJob]:
    """為每個收錄的險種建一個上傳工作，並先寫一筆「排隊中」，前端馬上看得到。"""
    jobs: list[IngestJob] = []
    for section in split_to_source(split).sections:
        if section.skip:
            continue
        job = IngestJob(
            filename=f"{split.filename}｜{section.name}",
            insurance_code=section.code,
            insurance_name=section.name,
        )
        session.add(job)
        await session.flush()
        session.add(
            IngestEvent(
                job_id=job.id,
                seq=1,
                step="extract",
                status="running",
                message="合訂本入庫排隊中，輪到時開始處理",
            )
        )
        jobs.append(job)
    await session.commit()
    return jobs


def section_range(source: SourceSpec, index: int) -> SectionRange:
    """第 index 個區段的範圍：從自己的標題行，到下一個區段（含不收的）的標題行之前。"""
    spec = source.sections[index]
    nxt = source.sections[index + 1] if index + 1 < len(source.sections) else None
    return SectionRange(
        first_page=spec.page,
        first_anchor=spec.anchor,
        end_page=nxt.page if nxt else None,
        end_anchor=nxt.anchor if nxt else None,
    )


async def run_bundle_ingest(
    engine: AsyncEngine,
    split_id: Any,
    job_ids: dict[str, Any],
    *,
    embeddings: Embeddings,
    model: str,
    confirmer: Confirmer,
) -> None:
    """依序處理每個險種（一個接一個，不同時打向量與 LLM 服務）。絕不往外 raise。

    job_ids：險種代碼 → 上傳工作的 id。
    """
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            split = (
                await session.exec(
                    select(BundleSplit).where(BundleSplit.id == split_id)
                )
            ).one()
            pdf = split_pdf(split)
            source = split_to_source(split)
            company = split.company or None
        try:
            sections = split_bundle(_pages(pdf), source)
        except ValueError as exc:
            await _fail_all(engine, job_ids, f"拆分清單切不出來：{exc}")
            return
    except Exception as exc:  # noqa: BLE001
        logger.exception("合訂本入庫失敗")
        await _fail_all(engine, job_ids, f"處理失敗：{exc}")
        return

    for index, section in enumerate(sections):
        if section.spec.skip or section.spec.code not in job_ids:
            continue
        await _guarded(
            engine,
            job_ids[section.spec.code],
            lambda session, job, emit, s=section, i=index: _run_section(
                session,
                job,
                emit,
                pdf,
                s,
                section_range(source, i),
                company,
                split.filename,
                embeddings,
                model,
                confirmer,
            ),
        )


async def _fail_all(engine: AsyncEngine, job_ids: dict[str, Any], message: str) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        for job_id in job_ids.values():
            job = (
                await session.exec(select(IngestJob).where(IngestJob.id == job_id))
            ).one()
            from app.ingest.agent import open_emitter

            emit = await open_emitter(session, job_id)
            await emit("done", "error", message)
            await _finish(session, job, "failed")


async def _run_section(
    session: AsyncSession,
    job: IngestJob,
    emit: Emitter,
    pdf: bytes,
    section: Section,
    rng: SectionRange,
    company: str | None,
    filename: str,
    embeddings: Embeddings,
    model: str,
    confirmer: Confirmer,
) -> None:
    last = max((c.page_end for c in section.chunks), default=section.spec.page)
    await emit(
        "extract",
        "ok",
        f"{filename} 第 {section.spec.page}–{last} 頁，{section.spec.name}",
    )
    await emit("classify", "ok", "合訂本的拆分清單已由管理者確認，不需要判斷是否為條款")
    articles = [c for c in section.chunks if c.kind == "article"]
    if not articles:
        await emit("chunk", "error", "這個險種一條「第N條」都切不出來")
        await emit("done", "error", "切不出條文，未寫入")
        await _finish(session, job, "failed")
        return
    await emit(
        "chunk",
        "ok",
        f"切出 {len(articles)} 條條文",
        current=len(articles),
        total=len(articles),
    )
    await _process(
        session,
        job,
        emit,
        pdf,
        articles,
        [],
        embeddings,
        model,
        confirmer,
        company,
        min_articles=1,  # 附加條款可能只有幾條；管理者已經確認過這是條款
        section=rng,
        approval=(section.approval_no, section.approval_date),
    )
    await _apply_policy_codes(session, section.spec.code, section.spec.policy_codes)


async def _apply_policy_codes(
    session: AsyncSession, code: str, policy_codes: dict[str, str]
) -> None:
    """管理者在確認畫面填的「章名 → 保單代碼」寫進險種；險種還沒入庫（全部待確認）就先不寫。"""
    filled = {chapter: c.strip() for chapter, c in policy_codes.items() if c.strip()}
    if not filled:
        return
    insurance = (
        await session.exec(select(Insurance).where(Insurance.code == code))
    ).first()
    if insurance is None:
        return
    insurance.policy_codes = {**insurance.policy_codes, **filled}
    session.add(insurance)
    await session.commit()
