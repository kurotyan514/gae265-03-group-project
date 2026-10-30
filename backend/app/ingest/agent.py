"""條款上傳 agent：PDF → 判斷是否為條款 → 切塊 → 驗證 → 算向量 → 入庫。

每個動作寫成一筆 IngestEvent（立刻 commit），SSE 路由讀這張表推給前端；
所以重整頁面或晚點才連線，都能把已發生的事件重放。流程由程式決定，LLM 只回答「是不是條款」。
"""

import logging
import tempfile
from collections.abc import Awaitable, Callable
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
from app.ingest.validate import validate_articles
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


async def run_ingest_job(
    engine: AsyncEngine,
    job_id: Any,
    pdf: bytes,
    *,
    embeddings: Embeddings,
    model: str,
    classifier: Classifier = llm_classify,
) -> None:
    """跑完整流程。背景工作在 request 結束後才執行，所以自己開 session，且絕不往外 raise。"""
    async with AsyncSession(engine, expire_on_commit=False) as session:
        job = (
            await session.exec(select(IngestJob).where(IngestJob.id == job_id))
        ).one()
        emit = Emitter(session, job_id)
        try:
            await _run(session, job, emit, pdf, embeddings, model, classifier)
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
    classifier: Classifier,
) -> None:
    await emit("extract", "running", f"讀取 {job.filename}")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "upload.pdf"
        path.write_bytes(pdf)
        pages = extract_pages(path)
    if not any(p.strip() for p in pages):
        await emit("extract", "error", "PDF 沒有可擷取的文字（可能是掃描檔，需要 OCR）")
        await _finish(session, job, "rejected")
        await emit("done", "error", "不是可處理的條款")
        return
    await emit(
        "extract", "ok", f"共 {len(pages)} 頁", current=len(pages), total=len(pages)
    )

    # 判斷：規則與 LLM 都要通過
    await emit("classify", "running", "判斷是否為保險條款")
    chunks = split_into_chunks(pages, COMPANY, job.filename, COMPANY)
    articles = [c for c in chunks if c.kind == "article"]
    if len(articles) < settings.INGEST_MIN_ARTICLES:
        reason = f"規則檢查：只找到 {len(articles)} 條「第N條」，少於 {settings.INGEST_MIN_ARTICLES}"
        await emit("classify", "error", reason, data={"by": "rule"})
        await _finish(session, job, "rejected")
        await emit("done", "error", "不是保險條款")
        return
    verdict = await classifier(_sample_text(pages, articles))
    if not verdict.is_policy:
        await emit(
            "classify",
            "error",
            f"LLM 判斷不是條款：{verdict.reason}",
            data={"by": "llm"},
        )
        await _finish(session, job, "rejected")
        await emit("done", "error", "不是保險條款")
        return
    await emit(
        "classify",
        "ok",
        f"是保險條款：{verdict.reason}",
        data={"insurance_name": verdict.insurance_name},
    )

    await emit(
        "chunk",
        "ok",
        f"切出 {len(articles)} 條條文",
        current=len(articles),
        total=len(articles),
    )

    # 驗證
    await emit("validate", "running", "驗證條文")
    issues = validate_articles(articles, min_articles=settings.INGEST_MIN_ARTICLES)
    errors = [i for i in issues if i.level == "error"]
    issue_data = {"issues": [{"level": i.level, "message": i.message} for i in issues]}
    if errors:
        await emit(
            "validate", "error", f"驗證未通過：{len(errors)} 個錯誤", data=issue_data
        )
        await _finish(session, job, "failed")
        await emit("done", "error", "驗證未通過，未寫入")
        return
    status = "warning" if issues else "ok"
    await emit("validate", status, f"驗證通過，{len(issues)} 個提醒", data=issue_data)

    # 向量 + 入庫
    spec = InsuranceSpec(code=job.insurance_code, name=job.insurance_name)
    rules = [
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

    summary = {"rules": result.rules, "embeddings": result.embeddings, "model": model}
    await _finish(session, job, "done", summary)
    await emit("done", "ok", "完成", data=summary)


async def fail_stale_jobs(engine: AsyncEngine) -> int:
    """伺服器重啟會中斷背景工作；把殘留的 running 標成 failed，前端才不會一直等。"""
    async with AsyncSession(engine, expire_on_commit=False) as session:
        jobs = (
            await session.exec(select(IngestJob).where(IngestJob.status == "running"))
        ).all()
        for job in jobs:
            last = (
                await session.exec(
                    select(IngestEvent.seq)
                    .where(IngestEvent.job_id == job.id)
                    .order_by(col(IngestEvent.seq).desc())
                    .limit(1)
                )
            ).first()
            emit = Emitter(session, job.id)
            emit.seq = last or 0
            await emit("done", "error", "伺服器重啟，處理中斷")
            await _finish(session, job, "failed")
        return len(jobs)
