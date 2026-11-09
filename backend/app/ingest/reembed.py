"""重新計算條文的向量：`embedding_text` 改了（例如加入章與節）之後，已經入庫的條文要重算才會套用。

    make reembed                          # 全部條文
    make reembed args="--insurance CHUBB06 --insurance HUANAN01"   # 只重算指定險種

只換目前設定的 embedding model 的那一筆向量，其他 model 留下的向量不動；條文本身（標題、內文、章、節）
完全不改。會呼叫 embedding 供應商（Azure OpenAI 會計費）。
"""

import argparse
import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence

from langchain_core.embeddings import Embeddings
from sqlmodel import col, delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.ingest.catalog import EMBED_BATCH, embedding_text
from app.models import Insurance, InsuranceRule, RuleEmbedding

logger = logging.getLogger(__name__)

Progress = Callable[[int, int], Awaitable[None]]


async def reembed_rules(
    session: AsyncSession,
    *,
    embeddings: Embeddings,
    model: str,
    insurance_codes: Sequence[str] | None = None,
    on_progress: Progress | None = None,
) -> int:
    """重算指定險種（不給就是全部）的條文向量，回傳重算幾條。

    向量先全部算好才寫入同一個 transaction：中途失敗（例如供應商斷線）不會留下算到一半的資料。
    """
    query = select(InsuranceRule, Insurance.name).join(Insurance)
    if insurance_codes:
        unknown = set(insurance_codes) - set(
            (await session.exec(select(Insurance.code))).all()
        )
        if unknown:
            raise ValueError(f"找不到這些險種：{', '.join(sorted(unknown))}")
        query = query.where(col(Insurance.code).in_(insurance_codes))
    rows = (
        await session.exec(
            query.order_by(col(Insurance.code), col(InsuranceRule.article_no))
        )
    ).all()

    texts = [embedding_text(name, rule) for rule, name in rows]
    vectors: list[list[float]] = []
    for start in range(0, len(texts), EMBED_BATCH):
        vectors.extend(
            await embeddings.aembed_documents(texts[start : start + EMBED_BATCH])
        )
        if on_progress:
            await on_progress(len(vectors), len(texts))

    rule_ids = [rule.id for rule, _ in rows]
    for start in range(0, len(rule_ids), 500):
        await session.exec(
            delete(RuleEmbedding).where(
                col(RuleEmbedding.rule_id).in_(rule_ids[start : start + 500]),
                col(RuleEmbedding.model) == model,
            )
        )
    session.add_all(
        RuleEmbedding(rule_id=rule_id, model=model, embedding=vector)
        for rule_id, vector in zip(rule_ids, vectors, strict=True)
    )
    await session.commit()
    return len(rows)


async def main() -> None:
    parser = argparse.ArgumentParser(description="重新計算條文的向量")
    parser.add_argument(
        "--insurance", action="append", metavar="代碼", help="只重算這個險種（可重複）"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    from app.core.db import engine
    from app.core.llm import embedding_model_name, get_embeddings

    model = embedding_model_name()

    async def progress(done: int, total: int) -> None:
        logger.info("已計算 %d／%d 條的向量", done, total)

    logger.info("重新計算向量（%s）…", model)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        count = await reembed_rules(
            session,
            embeddings=get_embeddings(),
            model=model,
            insurance_codes=args.insurance,
            on_progress=progress,
        )
    await engine.dispose()
    logger.info("完成：%d 條", count)


if __name__ == "__main__":
    asyncio.run(main())
