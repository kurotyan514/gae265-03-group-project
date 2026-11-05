"""條款上傳：收 PDF、背景跑 ingest agent、用 SSE 推進度。只在非 production 註冊（見 app.api.main）。"""

import asyncio
import json
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import SessionDep
from app.core import db
from app.core.config import settings
from app.core.llm import embedding_model_name, get_embeddings
from app.ingest import agent
from app.ingest.pending import load_pending
from app.ingest.review import ReviewError, review_article
from app.models import IngestEvent, IngestJob

router = APIRouter(prefix="/ingest", tags=["ingest"])

POLL_SECONDS = 0.5
FINISHED = {"done", "rejected", "needs_review", "failed"}


class IngestEventOut(BaseModel):
    seq: int
    step: str
    status: str = Field(description="running／ok／warning／error")
    message: str
    current: int | None
    total: int | None
    data: dict[str, Any] | None


class IngestJobOut(BaseModel):
    id: uuid.UUID
    filename: str
    insurance_code: str
    insurance_name: str
    status: str = Field(
        description="running／done／rejected（不是條款）／needs_review（待人工確認）／failed"
    )
    summary: dict[str, Any] | None
    created_at: datetime


class PendingArticleOut(BaseModel):
    article_no: int
    title: str
    chapter: str
    section: str | None
    content: str
    page_start: int
    page_end: int
    status: str = Field(description="pending／released／deleted")
    findings: list[dict[str, Any]] = Field(description="驗證沒通過的原因")
    edited: bool


class IngestJobDetail(IngestJobOut):
    events: list[IngestEventOut]
    articles: list[PendingArticleOut] = Field(
        description="待確認條文（內容驗證沒通過、停在切塊階段）；全部處理完後清空"
    )


class EditArticleIn(BaseModel):
    content: str = Field(min_length=1, description="修改後的條文內容")
    title: str | None = Field(default=None, description="要一併修改的標題（選填）")
    reason: str = Field(
        min_length=1, description="為什麼這樣改（例如：實際保單的寫法）"
    )


def _event_out(e: IngestEvent) -> IngestEventOut:
    return IngestEventOut(
        seq=e.seq,
        step=e.step,
        status=e.status,
        message=e.message,
        current=e.current,
        total=e.total,
        data=e.data,
    )


def _job_out(j: IngestJob) -> IngestJobOut:
    return IngestJobOut(
        id=j.id,
        filename=j.filename,
        insurance_code=j.insurance_code,
        insurance_name=j.insurance_name,
        status=j.status,
        summary=j.summary,
        created_at=j.created_at,
    )


async def _get_job(session: AsyncSession, job_id: uuid.UUID) -> IngestJob:
    job = await session.get(IngestJob, job_id)
    if job is None:
        raise HTTPException(404, "找不到這個上傳工作")
    return job


@router.post("/jobs", status_code=202)
async def create_ingest_job(
    session: SessionDep,
    background: BackgroundTasks,
    file: Annotated[UploadFile, File(description="條款 PDF")],
    insurance_code: Annotated[str, Form(min_length=1, examples=["FUBON07"])],
    insurance_name: Annotated[str, Form(min_length=1, examples=["旅遊不便險"])],
) -> IngestJobOut:
    """收下 PDF 並在背景開始處理；回傳 job，進度用 GET /ingest/jobs/{job_id}/events 訂閱。"""
    data = await file.read(settings.INGEST_MAX_UPLOAD_MB * 1024 * 1024 + 1)
    if len(data) > settings.INGEST_MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"檔案超過 {settings.INGEST_MAX_UPLOAD_MB} MB")
    if not data.startswith(b"%PDF-"):
        raise HTTPException(415, "只接受 PDF 檔")

    job = IngestJob(
        filename=file.filename or "upload.pdf",
        insurance_code=insurance_code.strip(),
        insurance_name=insurance_name.strip(),
    )
    session.add(job)
    await session.commit()
    background.add_task(
        agent.run_ingest_job,
        db.engine,
        job.id,
        data,
        embeddings=get_embeddings(),
        model=embedding_model_name(),
        classifier=agent.llm_classify,  # 在呼叫時才取，測試才換得掉
    )
    return _job_out(job)


@router.get("/jobs")
async def list_ingest_jobs(session: SessionDep) -> list[IngestJobOut]:
    """最近的上傳工作，新的在前。"""
    jobs = await session.exec(
        select(IngestJob).order_by(col(IngestJob.created_at).desc()).limit(50)
    )
    return [_job_out(j) for j in jobs]


@router.get("/jobs/{job_id}")
async def get_ingest_job(session: SessionDep, job_id: uuid.UUID) -> IngestJobDetail:
    """工作狀態與目前為止的全部事件（重整頁面後用來回看）。"""
    job = await _get_job(session, job_id)
    return await _detail(session, job)


async def _detail(session: AsyncSession, job: IngestJob) -> IngestJobDetail:
    events = await session.exec(
        select(IngestEvent)
        .where(IngestEvent.job_id == job.id)
        .order_by(col(IngestEvent.seq))
    )
    return IngestJobDetail(
        **_job_out(job).model_dump(),
        events=[_event_out(e) for e in events],
        articles=[
            PendingArticleOut(**a.model_dump(exclude={"insurance_code", "source_file"}))
            for a in load_pending(job)
        ],
    )


@router.post("/jobs/{job_id}/approve", status_code=202)
async def approve_ingest_job(
    session: SessionDep, background: BackgroundTasks, job_id: uuid.UUID
) -> IngestJobOut:
    """待人工確認（needs_review）的工作，忽略驗證錯誤仍然寫入；進度接續在同一個事件串流。"""
    job = await _get_job(session, job_id)
    if job.status != "needs_review" or not job.pending_rules:
        raise HTTPException(409, "這個工作不是待人工確認的狀態")
    job.status = "running"
    session.add(job)
    await session.commit()
    background.add_task(
        agent.resume_ingest_job,
        db.engine,
        job.id,
        embeddings=get_embeddings(),
        model=embedding_model_name(),
    )
    return _job_out(job)


async def _review(
    session: AsyncSession,
    job_id: uuid.UUID,
    article_no: int,
    action: str,
    **fields: Any,
) -> IngestJobDetail:
    # 鎖住這個工作：兩個人同時處理同一條時，後到的看到的是處理後的狀態（回 409）
    job = (
        await session.exec(
            select(IngestJob).where(IngestJob.id == job_id).with_for_update()
        )
    ).first()
    if job is None:
        raise HTTPException(404, "找不到這個上傳工作")
    try:
        await review_article(
            session,
            job,
            article_no,
            action,  # pyright: ignore[reportArgumentType]
            embeddings=get_embeddings(),
            model=embedding_model_name(),
            **fields,
        )
    except ReviewError as e:
        await session.rollback()
        raise HTTPException(e.status, e.message) from e
    except Exception as e:  # 向量服務失敗等：這一條維持待處理
        await session.rollback()
        raise HTTPException(502, f"處理失敗，這一條仍是待確認：{e}") from e
    await session.refresh(job)
    return await _detail(session, job)


@router.post("/jobs/{job_id}/articles/{article_no}/release")
async def release_pending_article(
    session: SessionDep, job_id: uuid.UUID, article_no: int
) -> IngestJobDetail:
    """放行一條待確認條文：只為這一條算向量並寫入，險種的其他條文不動。"""
    return await _review(session, job_id, article_no, "release")


@router.post("/jobs/{job_id}/articles/{article_no}/edit")
async def edit_pending_article(
    session: SessionDep, job_id: uuid.UUID, article_no: int, body: EditArticleIn
) -> IngestJobDetail:
    """修改一條待確認條文的文字後放行；視為管理者確認，不再重新驗證，舊字、新字與原因記在事件紀錄。"""
    return await _review(
        session,
        job_id,
        article_no,
        "edit",
        content=body.content,
        title=body.title,
        reason=body.reason,
    )


@router.post("/jobs/{job_id}/articles/{article_no}/delete")
async def delete_pending_article(
    session: SessionDep, job_id: uuid.UUID, article_no: int
) -> IngestJobDetail:
    """刪除一條待確認條文：不寫入資料庫。"""
    return await _review(session, job_id, article_no, "delete")


@router.get("/jobs/{job_id}/events", response_class=StreamingResponse)
async def stream_ingest_events(
    session: SessionDep, job_id: uuid.UUID, after: int = 0
) -> StreamingResponse:
    """SSE：先重放 seq > after 的事件，再持續推送新事件，job 結束後關閉連線。"""
    await _get_job(session, job_id)

    async def stream() -> AsyncGenerator[str]:
        last = after
        while True:
            async with AsyncSession(db.engine, expire_on_commit=False) as s:
                events = (
                    await s.exec(
                        select(IngestEvent)
                        .where(IngestEvent.job_id == job_id, IngestEvent.seq > last)
                        .order_by(col(IngestEvent.seq))
                    )
                ).all()
                status = (await s.get(IngestJob, job_id)).status  # pyright: ignore[reportOptionalMemberAccess]
            for e in events:
                last = e.seq
                payload = _event_out(e).model_dump_json()
                yield f"id: {e.seq}\nevent: ingest\ndata: {payload}\n\n"
            if status in FINISHED and not events:
                yield f"event: end\ndata: {json.dumps({'status': status})}\n\n"
                return
            await asyncio.sleep(POLL_SECONDS)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
