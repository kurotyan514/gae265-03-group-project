from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import col, select

from app.api.deps import SessionDep
from app.domain.rag.hybrid import MAX_K, RuleHit, search_rules
from app.models import Insurance, InsuranceRule

router = APIRouter(tags=["insurances"])


class InsuranceOut(BaseModel):
    code: str
    name: str
    rule_count: int


class RuleOut(BaseModel):
    insurance_code: str
    insurance_name: str
    article_no: int
    chapter: str
    title: str
    content: str = Field(description="條文原文")
    section: str | None = Field(description="所屬的章；附加條款沒有章")
    source_file: str
    page_start: int
    page_end: int


class SearchRequest(BaseModel):
    query: str
    k: int = Field(5, ge=1, le=MAX_K)
    insurance_codes: list[str] | None = Field(
        None, description="只搜尋這些險種；不填搜尋全部"
    )
    mode: Literal["hybrid", "vector", "keyword"] = "hybrid"
    expand_synonyms: bool = Field(
        False, description="先把口語補上條款用語再檢索（例如「偷」→「竊盜」）"
    )


class SearchHitOut(RuleOut):
    citation: str = Field(description="出處：險種、條號、標題、檔名與頁碼")
    score: float
    sources: list[Literal["vector", "keyword"]] = Field(description="由哪些檢索找到")
    similarity: float | None = Field(
        description="向量檢索的 cosine 相似度（0–1）；只有關鍵字命中時是 null"
    )


def _rule_out(rule: InsuranceRule, insurance: Insurance) -> RuleOut:
    return RuleOut(
        insurance_code=insurance.code,
        insurance_name=insurance.name,
        article_no=rule.article_no,
        chapter=rule.chapter,
        title=rule.title,
        content=rule.content,
        section=rule.section,
        source_file=rule.source_file,
        page_start=rule.page_start,
        page_end=rule.page_end,
    )


def _hit_out(hit: RuleHit) -> SearchHitOut:
    return SearchHitOut(
        insurance_code=hit.insurance_code,
        insurance_name=hit.insurance_name,
        article_no=hit.article_no,
        chapter=hit.chapter,
        title=hit.title,
        content=hit.content,
        section=hit.section,
        source_file=hit.source_file,
        page_start=hit.page_start,
        page_end=hit.page_end,
        citation=f"{hit.insurance_name} {hit.chapter} {hit.title}（{hit.source_file} 第 {hit.page_start} 頁）",
        score=hit.score,
        sources=[s for s in ("vector", "keyword") if s in hit.sources],
        similarity=hit.similarity,
    )


async def _get_insurance(session: SessionDep, code: str) -> Insurance:
    insurance = (
        await session.exec(select(Insurance).where(Insurance.code == code))
    ).first()
    if insurance is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"找不到險種「{code}」")
    return insurance


@router.get("/insurances")
async def list_insurances(session: SessionDep) -> list[InsuranceOut]:
    rows = (
        await session.exec(
            select(Insurance.code, Insurance.name, func.count(col(InsuranceRule.id)))
            .join(InsuranceRule, isouter=True)
            .group_by(col(Insurance.code), col(Insurance.name))
            .order_by(col(Insurance.code))
        )
    ).all()
    return [
        InsuranceOut(code=code, name=name, rule_count=count)
        for code, name, count in rows
    ]


@router.get("/insurances/{code}/rules")
async def list_insurance_rules(session: SessionDep, code: str) -> list[RuleOut]:
    insurance = await _get_insurance(session, code)
    rules = (
        await session.exec(
            select(InsuranceRule)
            .where(InsuranceRule.insurance_id == insurance.id)
            .order_by(col(InsuranceRule.article_no))
        )
    ).all()
    return [_rule_out(rule, insurance) for rule in rules]


@router.get("/insurances/{code}/rules/{article_no}")
async def get_insurance_rule(
    session: SessionDep, code: str, article_no: int
) -> RuleOut:
    insurance = await _get_insurance(session, code)
    rule = (
        await session.exec(
            select(InsuranceRule).where(
                InsuranceRule.insurance_id == insurance.id,
                InsuranceRule.article_no == article_no,
            )
        )
    ).first()
    if rule is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"{insurance.name}（{code}）沒有第 {article_no} 條",
        )
    return _rule_out(rule, insurance)


@router.post("/rules/search")
async def search_insurance_rules(
    session: SessionDep, body: SearchRequest
) -> list[SearchHitOut]:
    """混合檢索條文，回傳原文、分數與出處；原文不經 LLM。"""
    try:
        hits = await search_rules(
            session,
            body.query,
            k=body.k,
            insurance_codes=body.insurance_codes,
            mode=body.mode,
            expand_synonyms=body.expand_synonyms,
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    return [_hit_out(hit) for hit in hits]
