"""後台的「不收錄區」：看被設成不收錄的條文、單條（或整個險種）收錄回來、刪掉快照。

條文維護（`/admin/rules`、`/admin/insurances`）把條文設成不收錄時，會先把快照放進來；做錯了可以從這裡收錄回來，
不用整本重新上傳。整組只有管理者能用（#47）。
"""

import logging
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import col, select

from app.api.deps import AdminUser, SessionDep, require_admin
from app.core.llm import embedding_model_name, get_embeddings
from app.domain.excluded import EmbeddingFailed, restore
from app.models import ExcludedRule, Insurance, InsuranceRule

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/excluded", tags=["admin"], dependencies=[Depends(require_admin)]
)


class ExcludedOut(BaseModel):
    id: uuid.UUID
    insurance_code: str
    insurance_name: str
    article_no: int
    chapter: str
    title: str
    content: str
    section: str | None
    subsection: str | None
    reason: str | None
    excluded_at: datetime = Field(description="設成不收錄的時間")
    whole_insurance: bool = Field(description="是不是整個險種不收錄時一起存下來的")
    in_catalog: bool = Field(
        description="條文表裡現在已經有同一條（例如重新上傳又讀進來了），收錄會被略過"
    )
    insurance_exists: bool = Field(description="險種現在還在；不在的話收錄時會一併建立")


class ExcludedList(BaseModel):
    total: int
    items: list[ExcludedOut]


@router.get("")
async def list_excluded(
    session: SessionDep,
    insurance_code: Annotated[str | None, Query(description="只看這個險種")] = None,
    q: Annotated[str | None, Query(description="標題或內文包含這段文字")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ExcludedList:
    """不收錄區的條文（新的在前）。"""
    where = []
    if insurance_code:
        where.append(ExcludedRule.insurance_code == insurance_code)
    if q:
        where.append(
            col(ExcludedRule.title).icontains(q, autoescape=True)
            | col(ExcludedRule.content).icontains(q, autoescape=True)
        )
    total = await session.scalar(
        select(func.count()).select_from(ExcludedRule).where(*where)
    )
    rows = (
        await session.exec(
            select(ExcludedRule)
            .where(*where)
            .order_by(col(ExcludedRule.created_at).desc(), col(ExcludedRule.article_no))
            .limit(limit)
            .offset(offset)
        )
    ).all()
    present = set(
        (
            await session.exec(
                select(Insurance.code, InsuranceRule.article_no).join(
                    InsuranceRule, col(InsuranceRule.insurance_id) == col(Insurance.id)
                )
            )
        ).all()
    )
    codes = set((await session.exec(select(Insurance.code))).all())
    return ExcludedList(
        total=total or 0,
        items=[
            ExcludedOut(
                id=r.id,
                insurance_code=r.insurance_code,
                insurance_name=r.insurance_name,
                article_no=r.article_no,
                chapter=r.chapter,
                title=r.title,
                content=r.content,
                section=r.section,
                subsection=r.subsection,
                reason=r.reason,
                excluded_at=r.created_at,
                whole_insurance=r.whole_insurance,
                in_catalog=(r.insurance_code, r.article_no) in present,
                insurance_exists=r.insurance_code in codes,
            )
            for r in rows
        ],
    )


class RestoreIn(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


class RestoredRule(BaseModel):
    insurance_code: str
    article_no: int


class SkippedRule(RestoredRule):
    id: uuid.UUID
    reason: str


class RestoreOut(BaseModel):
    restored: list[RestoredRule]
    skipped: list[SkippedRule]
    insurances_created: list[str] = Field(
        description="因為險種已經不在而重新建立的險種代碼"
    )
    message: str


@router.post("/restore")
async def restore_excluded(
    session: SessionDep, user: AdminUser, body: RestoreIn
) -> RestoreOut:
    """把不收錄的條文收錄回來：重新寫入條文並只算這幾條的向量，成功的從不收錄區移除。

    條文表已經有同一條、險種名稱被別的險種佔用的會略過並說明原因，不影響其他的。向量服務失敗（502）時
    沒有任何改動。沿用原本的險種與條文 UUID。
    """
    items = (
        await session.exec(
            select(ExcludedRule).where(col(ExcludedRule.id).in_(body.ids))
        )
    ).all()
    missing = set(body.ids) - {i.id for i in items}
    if missing:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "有些快照找不到（可能已經收錄回來或被刪除）"
        )
    try:
        result = await restore(
            session, items, embeddings=get_embeddings(), model=embedding_model_name()
        )
    except EmbeddingFailed as exc:
        await session.rollback()
        logger.warning("收錄回來時重新計算向量失敗：%s", exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "向量服務無法使用，沒有任何條文被收錄回來"
        ) from exc
    await session.commit()
    logger.info(
        "不收錄的條文收錄回來：%s 條（略過 %s 條；使用者 %s）",
        len(result.restored),
        len(result.skipped),
        user.id,
    )
    parts = [f"已收錄回來 {len(result.restored)} 條"]
    if result.insurances_created:
        parts.append(f"重新建立險種 {'、'.join(result.insurances_created)}")
    if result.skipped:
        parts.append(f"略過 {len(result.skipped)} 條")
    return RestoreOut(
        restored=[
            RestoredRule(insurance_code=c, article_no=n) for c, n in result.restored
        ],
        skipped=[
            SkippedRule(
                id=s.id,
                insurance_code=s.insurance_code,
                article_no=s.article_no,
                reason=s.reason,
            )
            for s in result.skipped
        ],
        insurances_created=result.insurances_created,
        message="；".join(parts),
    )


class ExcludedDeleted(BaseModel):
    message: str


@router.delete("/{excluded_id}")
async def delete_excluded(
    session: SessionDep, user: AdminUser, excluded_id: uuid.UUID
) -> ExcludedDeleted:
    """從不收錄區永久刪除一份快照（之後就收錄不回來了；條文表不受影響）。"""
    row = await session.get(ExcludedRule, excluded_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到這份快照")
    await session.delete(row)
    await session.commit()
    logger.info(
        "不收錄區的快照已永久刪除：%s 第 %s 條（使用者 %s）",
        row.insurance_code,
        row.article_no,
        user.id,
    )
    return ExcludedDeleted(message="已從不收錄區刪除，之後收錄不回來了")
