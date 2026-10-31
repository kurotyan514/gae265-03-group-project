"""保單上傳（ADR-0009、0010）：收 PDF、抽文字，去識別化與切段在背景跑。原檔不落地、不存原檔名。"""

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlmodel import col, func, select

from app.api.deps import CurrentUser, SessionDep
from app.core import db
from app.core.config import settings
from app.models import Insurance, Policy, PolicyChunk, PolicyInsurance
from app.policy.extract import ExtractionError, PdfTextExtractor
from app.policy.pipeline import run_policy_pipeline

router = APIRouter(tags=["policies"])

PDF_MIME = "application/pdf"


class MatchedInsuranceOut(BaseModel):
    code: str
    name: str


class PolicyOut(BaseModel):
    id: uuid.UUID
    display_name: str
    status: str = Field(description="processing／ready／failed")
    error_message: str | None
    chunk_strategy: str | None = Field(description="article（依條號）／page（依頁）")
    chunk_count: int
    detected_company: str | None
    matched_insurances: list[MatchedInsuranceOut] = Field(
        description="程式從保單文字完全比對到的條款庫險種；比對不到就是空的"
    )
    created_at: datetime


async def _policy_out(session: SessionDep, policy: Policy) -> PolicyOut:
    chunk_count = (
        await session.exec(
            select(func.count(col(PolicyChunk.id))).where(
                PolicyChunk.policy_id == policy.id
            )
        )
    ).one()
    matched = (
        await session.exec(
            select(Insurance)
            .join(
                PolicyInsurance, col(PolicyInsurance.insurance_id) == col(Insurance.id)
            )
            .where(PolicyInsurance.policy_id == policy.id)
            .order_by(col(Insurance.code))
        )
    ).all()
    return PolicyOut(
        id=policy.id,
        display_name=policy.display_name,
        status=policy.status,
        error_message=policy.error_message,
        chunk_strategy=policy.chunk_strategy,
        chunk_count=chunk_count,
        detected_company=policy.detected_company,
        matched_insurances=[
            MatchedInsuranceOut(code=i.code, name=i.name) for i in matched
        ],
        created_at=policy.created_at,
    )


@router.post("/policies", status_code=status.HTTP_202_ACCEPTED)
async def create_policy(
    session: SessionDep,
    user: CurrentUser,
    background: BackgroundTasks,
    file: Annotated[UploadFile, File(description="保單 PDF（文字型）")],
) -> PolicyOut:
    """收下保單 PDF，抽文字後在背景去識別化、切段並比對險種；處理狀態用 GET /policies/{id} 查。"""
    limit = settings.POLICY_MAX_UPLOAD_MB * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"檔案超過 {settings.POLICY_MAX_UPLOAD_MB} MB",
        )
    if file.content_type != PDF_MIME or not data.startswith(b"%PDF-"):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "只接受 PDF 檔")
    try:
        pages = await asyncio.to_thread(PdfTextExtractor().extract, data)
    except ExtractionError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e

    policy = Policy(
        user_id=user.id,
        # 不用原檔名（可能含姓名）
        display_name=f"保單 {datetime.now(UTC):%Y-%m-%d %H:%M}",
    )
    session.add(policy)
    await session.commit()
    background.add_task(run_policy_pipeline, db.engine, policy.id, pages)
    return await _policy_out(session, policy)


@router.get("/policies/{policy_id}")
async def get_policy(
    session: SessionDep, user: CurrentUser, policy_id: uuid.UUID
) -> PolicyOut:
    policy = await session.get(Policy, policy_id)
    # 別人的保單跟不存在一樣回 404，不洩漏它存在
    if policy is None or policy.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到這份保單")
    return await _policy_out(session, policy)
