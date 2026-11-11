"""檢索自檢：條文入庫後，確認每一條真的檢索得到。

每一條用「標題＋第一句」當問題，限定在該險種內，用跟問答一樣的混合檢索；
自己出現在前 N 名就算通過。單條沒通過只是警告，不擋入庫；
整個險種的通過率低於門檻時標示「檢索品質異常」。N 與門檻是設定。

通過率以檢查當下該險種資料庫裡的條文為準；之後逐條放行的條文，由 `merge_article` 增量更新。
"""

import re
from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.embeddings import Embeddings
from pydantic import BaseModel, Field
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.domain.rag.hybrid import MAX_K, RuleHit, search_rules
from app.models import Insurance, InsuranceRule

FIRST_SENTENCE_CHARS = 120
Search = Callable[..., Awaitable[list[RuleHit]]]


class _BatchedEmbeddings(Embeddings):
    """問題一次批次算好向量，之後逐條檢索時直接取用，不必每條各打一次向量服務。"""

    def __init__(self, inner: Embeddings, vectors: dict[str, list[float]]) -> None:
        self.inner, self.vectors = inner, vectors

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.inner.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self.vectors.get(text) or self.inner.embed_query(text)

    async def aembed_query(self, text: str) -> list[float]:
        return self.vectors.get(text) or await self.inner.aembed_query(text)


class SelfCheck(BaseModel):
    top_n: int
    threshold: float
    checked: int
    passed: int
    rate: float = Field(description="通過率（0 到 1）；沒有檢查任何條文時為 1")
    abnormal: bool = Field(description="通過率低於門檻：這個險種的問答可能不可靠")
    failed: list[int] = Field(description="前 N 名找不到自己的條號")


def build_query(title: str, content: str) -> str:
    """標題（去掉【】）加上內文第一句。"""
    body = re.sub(r"\s+", "", content)
    first = body.split("。", 1)[0][:FIRST_SENTENCE_CHARS]
    return f"{title.strip('【】 ')} {first}".strip()


def summarize(
    checked: int, passed: int, failed: list[int], *, top_n: int, threshold: float
) -> SelfCheck:
    rate = passed / checked if checked else 1.0
    return SelfCheck(
        top_n=top_n,
        threshold=threshold,
        checked=checked,
        passed=passed,
        rate=round(rate, 4),
        abnormal=rate < threshold,
        failed=sorted(failed),
    )


async def check_articles(
    session: AsyncSession,
    code: str,
    article_nos: list[int] | None,
    *,
    embeddings: Embeddings,
    model: str,
    search: Search | None = None,
) -> tuple[int, list[int]]:
    """回傳（檢查幾條、沒通過的條號）。article_nos 是 None 就檢查該險種全部條文。"""
    stmt = (
        select(InsuranceRule.article_no, InsuranceRule.title, InsuranceRule.content)
        .join(Insurance)
        .where(Insurance.code == code)
        .order_by(col(InsuranceRule.article_no))
    )
    if article_nos is not None:
        stmt = stmt.where(col(InsuranceRule.article_no).in_(article_nos))
    rules = (await session.exec(stmt)).all()
    failed: list[int] = []
    queries = [build_query(title, content) for _, title, content in rules]
    if queries:
        vectors = await embeddings.aembed_documents(queries)
        embeddings = _BatchedEmbeddings(
            embeddings, dict(zip(queries, vectors, strict=True))
        )
    for (article_no, _, _), query in zip(rules, queries, strict=True):
        hits = await (search or search_rules)(
            session,
            query,
            k=min(settings.INGEST_SELFCHECK_TOP_N, MAX_K),
            insurance_codes=[code],
            embeddings=embeddings,
            model=model,
        )
        if not any(h.article_no == article_no for h in hits):
            failed.append(article_no)
    return len(rules), failed


async def check_insurance(
    session: AsyncSession,
    code: str,
    *,
    embeddings: Embeddings,
    model: str,
    search: Search | None = None,
) -> SelfCheck:
    checked, failed = await check_articles(
        session, code, None, embeddings=embeddings, model=model, search=search
    )
    return summarize(
        checked,
        checked - len(failed),
        failed,
        top_n=settings.INGEST_SELFCHECK_TOP_N,
        threshold=settings.INGEST_SELFCHECK_MIN_PASS_RATE,
    )


def merge_article(
    previous: dict[str, Any] | None, article_no: int, passed: bool
) -> SelfCheck:
    """逐條放行一條後增量更新：這一條是新入庫的，加進已檢查的條數。"""
    old = SelfCheck.model_validate(previous) if previous else None
    checked = (old.checked if old else 0) + 1
    ok = (old.passed if old else 0) + (1 if passed else 0)
    failed = [n for n in (old.failed if old else []) if n != article_no]
    if not passed:
        failed.append(article_no)
    return summarize(
        checked,
        ok,
        failed,
        top_n=settings.INGEST_SELFCHECK_TOP_N,
        threshold=settings.INGEST_SELFCHECK_MIN_PASS_RATE,
    )
