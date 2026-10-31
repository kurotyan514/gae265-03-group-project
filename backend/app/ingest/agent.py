"""條款上傳 agent：PDF → 判斷是否為條款 → 切塊 → 驗證 → 算向量 → 入庫。

每個動作寫成一筆 IngestEvent（立刻 commit），SSE 路由讀這張表推給前端；
所以重整頁面或晚點才連線，都能把已發生的事件重放。流程由程式決定，LLM 只回答「是不是條款」。
"""

import logging
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from langchain_core.embeddings import Embeddings
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.ingest.catalog import (
    COMPANY,
    InsuranceSpec,
    ParsedRule,
    article_label,
    import_catalog,
)
from app.ingest.clauses import Chunk, extract_pages, split_into_chunks
from app.ingest.validate import repair_articles, validate_articles
from app.models import IngestEvent, IngestJob

logger = logging.getLogger(__name__)

SAMPLE_PAGES = 2
SAMPLE_ARTICLES = 3
SAMPLE_CHARS = 1500


class Classification(BaseModel):
    is_policy: bool = Field(description="是否為保險條款（保險契約的條文本文）")
    reason: str = Field(description="一句話說明判斷理由")
    insurance_name: str | None = Field(
        default=None, description="條款上的險種名稱，看不出來為 None"
    )


Classifier = Callable[[str], Awaitable[Classification]]


async def llm_classify(sample: str) -> Classification:
    from app.core.llm import get_chat_model

    model = get_chat_model().with_structured_output(Classification)
    result = await model.ainvoke(
        "你是保險文件審查員。判斷以下文字節錄是否為『保險條款』（保險契約的條文，"
        "含條、款、項的條文結構）；投保說明、廣告、理賠申請書、一般文章都不算。"
        "只回答是否與理由，不要產生任何金額或數字。\n\n" + sample
    )
    return Classification.model_validate(result)


class Emitter:
    """把事件寫進資料庫；seq 由這裡遞增。"""

    def __init__(self, session: AsyncSession, job_id: Any) -> None:
        self.session = session
        self.job_id = job_id
        self.seq = 0

    async def __call__(
        self,
        step: str,
        status: str,
        message: str,
        *,
        current: int | None = None,
        total: int | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        self.seq += 1
        self.session.add(
            IngestEvent(
                job_id=self.job_id,
                seq=self.seq,
                step=step,
                status=status,
                message=message,
                current=current,
                total=total,
                data=data,
            )
        )
        await self.session.commit()


async def _finish(
    session: AsyncSession,
    job: IngestJob,
    status: str,
    summary: dict[str, Any] | None = None,
) -> None:
    job.status = status
    job.summary = summary
    session.add(job)
    await session.commit()


def _sample_text(pages: list[str], articles: list[Chunk]) -> str:
    head = "\n".join(pages[:SAMPLE_PAGES])[:SAMPLE_CHARS]
    body = "\n\n".join(c.text[:SAMPLE_CHARS] for c in articles[:SAMPLE_ARTICLES])
    return f"【開頭】\n{head}\n\n【條文抽樣】\n{body}"


def _split(
    pages: list[str], company: str, filename: str
) -> tuple[list[Chunk], list[str]]:
    """切塊。找不到以公司名開頭的商品標題行時，退回用第一行，並把這件事記進修復動作。"""
    try:
        return split_into_chunks(pages, company, filename, company), []
    except ValueError as exc:
        chunks = split_into_chunks(pages, company, filename, "")
        return chunks, [f"{exc}；改用第一行當商品標題"]


def _to_rules(articles: list[Chunk], spec: InsuranceSpec) -> list[ParsedRule]:
    return [
        ParsedRule(
            insurance_code=spec.code,
            article_no=c.article_no,
            chapter=article_label(c.article_no),
            title=c.article_title,
            content=c.text,
            section=c.chapter or None,
            source_file=c.source_file,
            page_start=c.page_start,
            page_end=c.page_end,
        )
        for c in sorted(articles, key=lambda c: c.article_no)
    ]


async def _emitter(session: AsyncSession, job_id: Any) -> Emitter:
    """從資料庫裡最後一個 seq 接續，人工確認後的第二段處理才不會從 1 重來。"""
    emit = Emitter(session, job_id)
    emit.seq = (
        await session.exec(
            select(IngestEvent.seq)
            .where(IngestEvent.job_id == job_id)
            .order_by(col(IngestEvent.seq).desc())
            .limit(1)
        )
    ).first() or 0
    return emit


async def run_ingest_job(
    engine: AsyncEngine,
    job_id: Any,
    pdf: bytes,
    *,
    embeddings: Embeddings,
    model: str,
    company: str = COMPANY,
    classifier: Classifier = llm_classify,
) -> None:
    """跑完整流程。背景工作在 request 結束後才執行，所以自己開 session，且絕不往外 raise。"""
    await _guarded(
        engine,
        job_id,
        lambda session, job, emit: _run(
            session, job, emit, pdf, embeddings, model, company, classifier
        ),
    )


async def resume_ingest_job(
    engine: AsyncEngine, job_id: Any, *, embeddings: Embeddings, model: str
) -> None:
    """人工確認「仍然寫入」後，把暫存的條文算向量並入庫（跳過驗證）。"""
    await _guarded(
        engine,
        job_id,
        lambda session, job, emit: _resume(session, job, emit, embeddings, model),
    )


async def _guarded(
    engine: AsyncEngine, job_id: Any, work: Callable[..., Awaitable[None]]
) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        job = (
            await session.exec(select(IngestJob).where(IngestJob.id == job_id))
        ).one()
        emit = await _emitter(session, job_id)
        try:
            await work(session, job, emit)
        except Exception as exc:
            logger.exception("ingest job %s 失敗", job_id)
            await session.rollback()
            await emit("done", "error", f"處理失敗：{exc}")
            await _finish(session, job, "failed")


async def _run(
    session: AsyncSession,
    job: IngestJob,
    emit: Emitter,
    pdf: bytes,
    embeddings: Embeddings,
    model: str,
    company: str,
    classifier: Classifier,
) -> None:
    await emit("extract", "running", f"讀取 {job.filename}")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "upload.pdf"
        path.write_bytes(pdf)
        pages = extract_pages(path)
    if not any(p.strip() for p in pages):
        await emit("extract", "error", "PDF 沒有可擷取的文字（可能是掃描檔，需要 OCR）")
        await emit("done", "error", "無法處理，未寫入")
        await _finish(session, job, "failed")
        return
    await emit(
        "extract", "ok", f"共 {len(pages)} 頁", current=len(pages), total=len(pages)
    )

    # 判斷：只有 LLM 認定不是條款才拒絕；結構不完整的條款交給後面的修復與人工確認
    await emit("classify", "running", "判斷是否為保險條款")
    chunks, notes = _split(pages, company, job.filename)
    articles = [c for c in chunks if c.kind == "article"]
    verdict = await classifier(_sample_text(pages, articles))
    if not verdict.is_policy:
        await emit(
            "classify",
            "error",
            f"LLM 判斷不是條款：{verdict.reason}",
            data={"by": "llm"},
        )
        await emit("done", "error", "不是保險條款")
        await _finish(session, job, "rejected")
        return
    await emit(
        "classify",
        "ok",
        f"是保險條款：{verdict.reason}",
        data={"insurance_name": verdict.insurance_name},
    )

    if not articles:
        await emit("chunk", "error", "是條款，但一條「第N條」都切不出來")
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

    # 修復：驗證有錯誤，或切塊時退而求其次過，才走這一步
    issues = validate_articles(articles, min_articles=settings.INGEST_MIN_ARTICLES)
    if notes or any(i.level == "error" for i in issues):
        await emit("repair", "running", "自動修復")
        articles, actions = repair_articles(articles)
        actions = notes + actions
        issues = validate_articles(articles, min_articles=settings.INGEST_MIN_ARTICLES)
        await emit(
            "repair",
            "warning" if actions else "ok",
            f"修復 {len(actions)} 項" if actions else "沒有可自動修復的項目",
            data={"actions": actions},
        )

    errors = [i for i in issues if i.level == "error"]
    issue_data = {"issues": [{"level": i.level, "message": i.message} for i in issues]}
    spec = InsuranceSpec(code=job.insurance_code, name=job.insurance_name)
    if errors:
        await emit(
            "validate", "error", f"驗證未通過：{len(errors)} 個錯誤", data=issue_data
        )
        if not articles:
            await emit("done", "error", "沒有可用的條文，未寫入")
            await _finish(session, job, "failed")
            return
        job.pending_rules = [asdict(r) for r in _to_rules(articles, spec)]
        await emit(
            "done",
            "warning",
            "驗證未通過，等待人工確認",
            data={"pending": len(articles)},
        )
        await _finish(session, job, "needs_review", {"pending": len(articles)})
        return
    status = "warning" if issues else "ok"
    await emit("validate", status, f"驗證通過，{len(issues)} 個提醒", data=issue_data)

    await _import(
        session, job, emit, spec, _to_rules(articles, spec), embeddings, model
    )


async def _resume(
    session: AsyncSession,
    job: IngestJob,
    emit: Emitter,
    embeddings: Embeddings,
    model: str,
) -> None:
    rules = [ParsedRule(**r) for r in job.pending_rules or []]
    if not rules:
        raise ValueError("沒有待確認的條文")
    await emit(
        "validate", "warning", f"人工確認：忽略驗證錯誤，仍然寫入 {len(rules)} 條"
    )
    spec = InsuranceSpec(code=job.insurance_code, name=job.insurance_name)
    await _import(session, job, emit, spec, rules, embeddings, model)


async def _import(
    session: AsyncSession,
    job: IngestJob,
    emit: Emitter,
    spec: InsuranceSpec,
    rules: list[ParsedRule],
    embeddings: Embeddings,
    model: str,
) -> None:
    async def on_embed(done: int, total: int) -> None:
        await emit(
            "embed", "running", f"計算向量 {done}/{total}", current=done, total=total
        )

    await emit("embed", "running", "計算向量", current=0, total=len(rules))
    result = await import_catalog(
        session,
        [spec],
        rules,
        embeddings=embeddings,
        model=model,
        on_embed_progress=on_embed,
    )
    await emit(
        "embed",
        "ok",
        f"完成 {result.embeddings} 筆向量（{model}）",
        current=result.embeddings,
        total=result.embeddings,
    )
    await emit("import", "ok", f"寫入 {spec.code} {spec.name}：{result.rules} 條條文")

    job.pending_rules = None
    summary = {"rules": result.rules, "embeddings": result.embeddings, "model": model}
    await emit("done", "ok", "完成", data=summary)
    await _finish(session, job, "done", summary)


async def fail_stale_jobs(engine: AsyncEngine) -> int:
    """伺服器重啟會中斷背景工作；把殘留的 running 標成 failed，前端才不會一直等。"""
    async with AsyncSession(engine, expire_on_commit=False) as session:
        jobs = (
            await session.exec(select(IngestJob).where(IngestJob.status == "running"))
        ).all()
        for job in jobs:
            emit = await _emitter(session, job.id)
            await emit("done", "error", "伺服器重啟，處理中斷")
            await _finish(session, job, "failed")
        return len(jobs)
