"""混合檢索：向量（抓語意）＋ BM25（抓字面詞），用 RRF 合併名次。

查詢的是資料庫裡的條文（InsuranceRule）。BM25 索引從條文建在記憶體裡，條文有變動（重新匯入）
就會自動重建。向量只搜尋目前設定的 embedding model 產生的那一批。
"""

import re
import uuid
from dataclasses import dataclass
from typing import Literal

from langchain_core.embeddings import Embeddings
from sqlalchemy import func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.llm import embedding_model_name, get_embeddings
from app.domain.rag.keyword import BM25Index
from app.domain.rag.synonyms import expand_with_synonyms, load_synonyms
from app.ingest.catalog import embedding_text
from app.models import Insurance, InsuranceRule, RuleEmbedding

RRF_K = 60
MAX_K = 50
Mode = Literal["hybrid", "vector", "keyword"]


@dataclass(frozen=True)
class RuleHit:
    rule_id: uuid.UUID
    insurance_code: str
    insurance_name: str
    article_no: int
    chapter: str
    title: str
    content: str
    section: str | None
    source_file: str
    page_start: int
    page_end: int
    score: float
    sources: list[str]  # "vector"、"keyword"，或兩者
    similarity: float | None = (
        None  # 向量檢索的 cosine 相似度（0–1）；只有關鍵字命中時是 None
    )


def rrf_merge(rankings: list[list[str]], k: int = RRF_K) -> list[tuple[str, float]]:
    """每條路線是依名次排好的 id 清單。分數 = 各路線 1/(k+名次) 的總和，名次從 1 起算。"""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, id_ in enumerate(ranking, start=1):
            scores[id_] = scores.get(id_, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


@dataclass(frozen=True)
class _KeywordIndex:
    fingerprint: tuple[int, object]
    bm25: BM25Index
    owner: dict[str, uuid.UUID]  # 條文 id → 險種 id，篩選險種用


_index_cache: _KeywordIndex | None = None


async def _keyword_index(session: AsyncSession) -> _KeywordIndex:
    """條文的筆數或最後更新時間變了就重建，所以重新匯入後不必重啟。"""
    global _index_cache
    count, latest = (
        await session.exec(select(func.count(), func.max(InsuranceRule.updated_at)))
    ).one()
    if _index_cache is None or _index_cache.fingerprint != (count, latest):
        rows = (
            await session.exec(select(InsuranceRule, Insurance.name).join(Insurance))
        ).all()
        _index_cache = _KeywordIndex(
            fingerprint=(count, latest),
            bm25=BM25Index(
                [(str(rule.id), embedding_text(name, rule)) for rule, name in rows]
            ),
            owner={str(rule.id): rule.insurance_id for rule, _ in rows},
        )
    return _index_cache


def _validate(query: str, k: int, mode: str) -> None:
    if not re.search(r"\w", query):  # 空字串、只有空白或標點
        raise ValueError("查詢不可為空")
    if not 1 <= k <= MAX_K:
        raise ValueError(f"k 必須在 1–{MAX_K} 之間，收到 {k}")
    if mode not in ("hybrid", "vector", "keyword"):
        raise ValueError(f"mode 必須是 hybrid、vector 或 keyword，收到「{mode}」")


async def _insurance_ids(session: AsyncSession, codes: list[str]) -> set[uuid.UUID]:
    known = dict((await session.exec(select(Insurance.code, Insurance.id))).all())
    unknown = [c for c in codes if c not in known]
    if unknown:
        raise ValueError(
            f"找不到險種「{'、'.join(unknown)}」，可用的險種：{'、'.join(sorted(known))}"
        )
    return {known[c] for c in codes}


async def _vector_ranking(
    session: AsyncSession,
    query: str,
    n: int,
    allowed: set[uuid.UUID] | None,
    embeddings: Embeddings | None,
    model: str,
) -> list[tuple[str, float]]:
    """(條文 id, cosine 相似度)，由近到遠。"""
    vector = await (embeddings or get_embeddings()).aembed_query(query)
    distance = col(RuleEmbedding.embedding).cosine_distance(vector)  # pyright: ignore[reportAttributeAccessIssue]
    stmt = (
        select(RuleEmbedding.rule_id, distance)
        .join(InsuranceRule, col(InsuranceRule.id) == col(RuleEmbedding.rule_id))
        .where(RuleEmbedding.model == model)
        .order_by(distance)
        .limit(n)
    )
    if allowed is not None:
        stmt = stmt.where(col(InsuranceRule.insurance_id).in_(allowed))
    return [
        (str(rule_id), min(1.0, max(0.0, 1.0 - float(dist))))
        for rule_id, dist in (await session.exec(stmt)).all()
    ]


async def search_rules(
    session: AsyncSession,
    query: str,
    *,
    k: int = 5,
    insurance_codes: list[str] | None = None,
    mode: Mode = "hybrid",
    expand_synonyms: bool = False,
    embeddings: Embeddings | None = None,
    model: str | None = None,
) -> list[RuleHit]:
    _validate(query, k, mode)
    if expand_synonyms:
        query = expand_with_synonyms(query, load_synonyms())
    allowed = (
        await _insurance_ids(session, insurance_codes) if insurance_codes else None
    )
    fetch_n = max(k * 3, 15)

    similarity: dict[str, float] = {}
    keyword_scores: dict[str, float] = {}
    if mode in ("hybrid", "vector"):
        found = await _vector_ranking(
            session,
            query,
            fetch_n,
            allowed,
            embeddings,
            model or embedding_model_name(),
        )
        similarity = dict(found)
    if mode in ("hybrid", "keyword"):
        index = await _keyword_index(session)
        for rule_id, score in index.bm25.search(query, k=len(index.bm25)):
            if len(keyword_scores) < fetch_n and (
                allowed is None or index.owner[rule_id] in allowed
            ):
                keyword_scores[rule_id] = score

    routes = {"vector": list(similarity), "keyword": list(keyword_scores)}
    match mode:
        case "hybrid":
            ranked = rrf_merge([routes["vector"], routes["keyword"]])
        case "vector":
            ranked = list(similarity.items())
        case "keyword":
            ranked = list(keyword_scores.items())

    top = ranked[:k]
    rows = await _load_rules(session, [uuid.UUID(rule_id) for rule_id, _ in top])
    hits = []
    for rule_id, score in top:
        rule, insurance = rows[rule_id]
        hits.append(
            RuleHit(
                rule_id=rule.id,
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
                score=score,
                sources=[
                    name for name in ("vector", "keyword") if rule_id in routes[name]
                ],
                similarity=similarity.get(rule_id),
            )
        )
    return hits


async def _load_rules(
    session: AsyncSession, ids: list[uuid.UUID]
) -> dict[str, tuple[InsuranceRule, Insurance]]:
    if not ids:
        return {}
    rows = (
        await session.exec(
            select(InsuranceRule, Insurance)
            .join(Insurance)
            .where(col(InsuranceRule.id).in_(ids))
        )
    ).all()
    return {str(rule.id): (rule, insurance) for rule, insurance in rows}
