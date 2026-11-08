"""後台的條文維護：瀏覽條文與向量狀態、修改標題與內文並重新計算這一條的向量。

和 `/ingest` 一樣整組只有管理者能用（沒登入 401、不是管理者 403）、所有環境都註冊（ADR-0023、#47）。開發用的唯讀清單在 `/rules`（只有非 production）。
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import col, select

from app.api.deps import AdminUser, SessionDep, require_admin
from app.api.routes.dev import DevRuleList, DevRuleOut, rules_with_vector_status
from app.api.routes.insurances import _rule_out
from app.core.llm import embedding_model_name, get_embeddings
from app.domain.plans import load_plans
from app.ingest.catalog import embedding_text
from app.models import (
    BundleSplit,
    ConversationInsurance,
    IncidentClause,
    Insurance,
    InsuranceRule,
    PolicyAddon,
    RuleEmbedding,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/rules", tags=["admin"], dependencies=[Depends(require_admin)]
)


@router.get("")
async def list_admin_rules(
    session: SessionDep,
    insurance_code: Annotated[
        str | None, Query(description="只看這個險種", examples=["FUBON05"])
    ] = None,
    q: Annotated[
        str | None, Query(description="標題或內文包含這段文字", examples=["除外責任"])
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DevRuleList:
    """全部條文（依險種代碼、條號排序），含向量狀態。"""
    return await rules_with_vector_status(session, insurance_code, q, limit, offset)


class RulePatch(BaseModel):
    title: str | None = Field(
        default=None, max_length=200, description="新的標題；沒給就不改"
    )
    content: str | None = Field(default=None, description="新的內文；沒給就不改")
    reason: str | None = Field(
        default=None, max_length=200, description="為什麼改（只寫進日誌，不存資料庫）"
    )


@router.patch("/{insurance_code}/{article_no}")
async def edit_admin_rule(
    session: SessionDep,
    user: AdminUser,
    insurance_code: str,
    article_no: int,
    body: RulePatch,
) -> DevRuleOut:
    """修改一條條文的標題與內文，並重新計算這一條的向量。

    標題與內文都進檢索用的文字（`embedding_text`），所以向量先算好才寫入：向量服務失敗（502）時
    標題、內文都不會動。其他 model 留下的舊向量對不上新內容，一併刪除，只留目前設定的 model。
    BM25 索引靠條文的 `updated_at` 變動自動重建，不必另外處理。
    改動只存在資料庫：重新上傳合訂本或 `make ingest` 會用 PDF 的內容蓋回去。
    """
    row = (
        await session.exec(
            select(InsuranceRule, Insurance)
            .join(Insurance)
            .where(
                Insurance.code == insurance_code, InsuranceRule.article_no == article_no
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到這一條")
    rule, insurance = row

    title = rule.title if body.title is None else body.title.strip()
    content = rule.content if body.content is None else body.content.strip()
    if not title:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "標題不可以是空的")
    if not content:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "內文不可以是空的")
    if title == rule.title and content == rule.content:
        raise HTTPException(status.HTTP_409_CONFLICT, "標題與內文都沒有變動")

    old = (rule.title, len(rule.content))
    rule.title, rule.content = title, content
    try:
        vector = (
            await get_embeddings().aembed_documents(
                [embedding_text(insurance.name, rule)]
            )
        )[0]
    except Exception as exc:
        await session.rollback()  # 還沒寫入，只是放掉讀到的條文
        logger.warning(
            "條文 %s 第 %s 條重新計算向量失敗：%s", insurance_code, article_no, exc
        )
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "向量服務無法使用，標題與內文都沒有修改"
        ) from exc

    model = embedding_model_name()
    for old_embedding in (
        await session.exec(
            select(RuleEmbedding).where(RuleEmbedding.rule_id == rule.id)
        )
    ).all():
        await session.delete(old_embedding)
    await session.flush()
    session.add(rule)
    session.add(RuleEmbedding(rule_id=rule.id, model=model, embedding=vector))
    await session.commit()
    await session.refresh(rule)
    logger.info(
        "條文已修改並重新計算向量：%s 第 %s 條（原標題「%s」、原內文 %s 字；使用者 %s；原因：%s）",
        insurance_code,
        article_no,
        old[0],
        old[1],
        user.id,
        body.reason or "未填",
    )
    return DevRuleOut(
        **_rule_out(rule, insurance).model_dump(),
        embedding_models=[model],
        embedding_dimensions=len(vector),
    )


class RuleDeleted(BaseModel):
    insurance_code: str
    article_no: int
    message: str


@router.delete("/{insurance_code}/{article_no}")
async def delete_admin_rule(
    session: SessionDep,
    user: AdminUser,
    insurance_code: str,
    article_no: int,
    reason: Annotated[
        str | None, Query(max_length=200, description="為什麼不收錄（只寫進日誌）")
    ] = None,
) -> RuleDeleted:
    """不收錄一條條文：刪掉這一條，向量與問答出處（`message_citation`）跟著刪。

    只動資料庫：重新上傳合訂本或 `make ingest` 會把它再讀進來。要長久不收錄，請在合訂本確認畫面
    取消這份條款的收錄，或把條文改掉。
    """
    row = (
        await session.exec(
            select(InsuranceRule)
            .join(Insurance)
            .where(
                Insurance.code == insurance_code, InsuranceRule.article_no == article_no
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到這一條")
    title = row.title
    await session.delete(row)
    await session.commit()
    logger.info(
        "條文已不收錄：%s 第 %s 條「%s」（使用者 %s；原因：%s）",
        insurance_code,
        article_no,
        title,
        user.id,
        reason or "未填",
    )
    return RuleDeleted(
        insurance_code=insurance_code,
        article_no=article_no,
        message="已刪除這一條；重新上傳合訂本會再讀進來",
    )


insurances_router = APIRouter(
    prefix="/admin/insurances", tags=["admin"], dependencies=[Depends(require_admin)]
)


class InsuranceDeleted(BaseModel):
    insurance_code: str
    rules_deleted: int
    in_bundles: list[str] = Field(
        description="還把這個險種列為「收錄」的合訂本拆分清單檔名；重新入庫它會再進來，要到拆分清單取消收錄"
    )
    message: str


@insurances_router.delete("/{insurance_code}")
async def delete_admin_insurance(
    session: SessionDep,
    user: AdminUser,
    insurance_code: str,
    reason: Annotated[
        str | None, Query(max_length=200, description="為什麼不收錄（只寫進日誌）")
    ] = None,
) -> InsuranceDeleted:
    """不收錄整個險種：刪掉險種與它全部的條文、向量與問答出處。

    還被用到的險種不給刪（409，列出誰在用），避免把別人的資料一起帶走：方案（plans.json）、
    保單的加購、事件的保障結論（incident_clause，資料庫本來就擋）、方案問答的對話。
    """
    insurance = (
        await session.exec(select(Insurance).where(Insurance.code == insurance_code))
    ).first()
    if insurance is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到這個險種")

    used_by: list[str] = []
    plans = [p.name for p in load_plans() if insurance_code in p.insurance_codes]
    if plans:
        used_by.append(f"方案：{'、'.join(plans)}")
    for label, model in (
        ("保單的加購", PolicyAddon),
        ("事件的保障結論", IncidentClause),
        ("方案問答的對話", ConversationInsurance),
    ):
        count = (
            await session.exec(
                select(func.count())
                .select_from(model)
                .where(col(model.insurance_id) == insurance.id)
            )
        ).one()
        if count:
            used_by.append(f"{label} {count} 筆")
    if used_by:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{insurance_code} 還在使用中，不能不收錄：{'；'.join(used_by)}",
        )

    rules = (
        await session.exec(
            select(func.count())
            .select_from(InsuranceRule)
            .where(col(InsuranceRule.insurance_id) == insurance.id)
        )
    ).one()
    in_bundles = [
        split.filename
        for split in (await session.exec(select(BundleSplit))).all()
        if any(
            sec.get("code") == insurance_code and not sec.get("skip")
            for sec in split.sections
        )
    ]
    await session.delete(
        insurance
    )  # 條文、向量、出處由資料庫的 ON DELETE CASCADE 一起刪
    await session.commit()
    logger.info(
        "險種已不收錄：%s（%s 條；使用者 %s；原因：%s）",
        insurance_code,
        rules,
        user.id,
        reason or "未填",
    )
    return InsuranceDeleted(
        insurance_code=insurance_code,
        rules_deleted=rules,
        in_bundles=in_bundles,
        message=(
            "已刪除；"
            + (
                f"但合訂本拆分清單（{'、'.join(in_bundles)}）還把它列為收錄，重新入庫會再進來"
                if in_bundles
                else "沒有拆分清單把它列為收錄"
            )
        ),
    )
