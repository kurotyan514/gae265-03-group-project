from typing import Annotated, Literal

from fastapi import APIRouter, Body, HTTPException, Path, status
from fastapi.openapi.models import Example
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import col, select

from app.api.deps import SessionDep
from app.domain.rag.hybrid import MAX_K, RuleHit, search_rules
from app.models import Insurance, InsuranceRule

router = APIRouter(tags=["insurances"])

# Swagger（/docs）上的範例，可以直接按 Try it out
SEARCH_EXAMPLES: dict[str, Example] = {
    "colloquial": {
        "summary": "口語問句（混合檢索）：手機被偷",
        "value": {"query": "手機被偷", "k": 3},
    },
    "ski": {
        "summary": "滑雪受傷會不會賠",
        "value": {"query": "滑雪受傷，意外傷害醫療會不會賠？", "k": 5},
    },
    "keyword": {
        "summary": "只用關鍵字（BM25）：班機延誤",
        "value": {"query": "班機延誤", "mode": "keyword", "k": 5},
    },
    "vector": {
        "summary": "只用向量（語意）：行李遲遲沒出來",
        "value": {"query": "下飛機後行李遲遲沒出來", "mode": "vector", "k": 5},
    },
    "synonyms": {
        "summary": "先展開同義詞再檢索（口語「偷」→條文的「竊盜」）",
        "value": {"query": "手機被偷", "mode": "hybrid", "expand_synonyms": True},
    },
    "one-insurance": {
        "summary": "只搜尋指定險種（T113 行動電話被竊、T068 旅行平安）",
        "value": {"query": "不賠的情形", "insurance_codes": ["T113", "T068"], "k": 5},
    },
}
CODE_EXAMPLES: dict[str, Example] = {
    "phone": {"summary": "行動電話被竊損失保險", "value": "T113"},
    "accident": {"summary": "旅行平安保險", "value": "T068"},
    "illness": {"summary": "海外突發疾病醫療健康保險", "value": "T147"},
}
ARTICLE_EXAMPLES: dict[str, Example] = {
    "first": {"summary": "第 1 條", "value": 1},
    "twenty-five": {"summary": "第 25 條（條號會跳號）", "value": 25},
}
CodePath = Annotated[
    str, Path(description="險種代碼（insCode）", openapi_examples=CODE_EXAMPLES)
]
ArticlePath = Annotated[
    int,
    Path(description="條號（沿用商品條款，會跳號）", openapi_examples=ARTICLE_EXAMPLES),
]


APPROVAL_NO = Field(
    description="主管機關核准／備查文號；回答時必須附上，沒有文號的險種是 null"
)
APPROVAL_DATE = Field(description="文號日期（民國年.月.日）")


class InsuranceOut(BaseModel):
    code: str
    name: str
    approval_no: str | None = APPROVAL_NO
    approval_date: str | None = APPROVAL_DATE
    rule_count: int


class RuleOut(BaseModel):
    insurance_code: str
    insurance_name: str
    approval_no: str | None = APPROVAL_NO
    approval_date: str | None = APPROVAL_DATE
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
        approval_no=insurance.approval_no,
        approval_date=insurance.approval_date,
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
        approval_no=hit.approval_no,
        approval_date=hit.approval_date,
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
            select(Insurance, func.count(col(InsuranceRule.id)))
            .join(InsuranceRule, isouter=True)
            .group_by(col(Insurance.id))
            .order_by(col(Insurance.code))
        )
    ).all()
    return [
        InsuranceOut(
            code=i.code,
            name=i.name,
            approval_no=i.approval_no,
            approval_date=i.approval_date,
            rule_count=count,
        )
        for i, count in rows
    ]


@router.get("/insurances/{code}/rules")
async def list_insurance_rules(session: SessionDep, code: CodePath) -> list[RuleOut]:
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
    session: SessionDep, code: CodePath, article_no: ArticlePath
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
    session: SessionDep,
    body: Annotated[SearchRequest, Body(openapi_examples=SEARCH_EXAMPLES)],
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
