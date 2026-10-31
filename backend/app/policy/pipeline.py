"""保單處理管線：已抽好的頁面文字 → 去識別化 → 切段 → 險種比對 → 寫入。

原檔不落地（ADR-0009）：呼叫端只把抽出的文字交進來。使用者輸入與保單內容不寫進 log，
失敗時 log 與 `policy.error_message` 都只放固定說明，不放例外訊息（可能夾著內容）。
"""

import logging
import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Insurance, Policy, PolicyChunk, PolicyInsurance
from app.policy.chunking import chunk_policy
from app.policy.deidentify import deidentify_pages
from app.policy.extract import PageText
from app.policy.matching import CatalogInsurance, detect_company, match_insurances

logger = logging.getLogger(__name__)

FAILED_MESSAGE = "保單處理失敗，請稍後再試或換一份檔案"


async def run_policy_pipeline(
    engine: AsyncEngine, policy_id: uuid.UUID, pages: Sequence[PageText]
) -> None:
    """背景工作在 request 結束後才執行，所以自己開 session，且絕不往外 raise。"""
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await _process(session, policy_id, pages)
    except Exception as e:
        logger.error("保單 %s 處理失敗：%s", policy_id, type(e).__name__)
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                policy = await session.get(Policy, policy_id)
                if policy is not None:
                    policy.status = "failed"
                    policy.error_message = FAILED_MESSAGE
                    session.add(policy)
                    await session.commit()
        except Exception as e2:
            logger.error("保單 %s 狀態寫入失敗：%s", policy_id, type(e2).__name__)


async def _process(
    session: AsyncSession, policy_id: uuid.UUID, pages: Sequence[PageText]
) -> None:
    policy = await session.get(Policy, policy_id)
    if policy is None:
        return
    texts = deidentify_pages([p.text for p in pages], [p.layout_text for p in pages])
    numbered = [(p.page_no, t) for p, t in zip(pages, texts, strict=True)]
    full_text = "\n".join(texts)

    company = detect_company(full_text)
    strategy, drafts = chunk_policy(numbered)
    catalog = [
        CatalogInsurance(i.id, i.code, i.name)
        for i in (await session.exec(select(Insurance))).all()
    ]
    matched = match_insurances(full_text, catalog)

    session.add_all(
        PolicyChunk(
            policy_id=policy.id,
            user_id=policy.user_id,
            idx=idx,
            page_start=d.page_start,
            page_end=d.page_end,
            article_no=d.article_no,
            content=d.content,
        )
        for idx, d in enumerate(drafts)
    )
    session.add_all(
        PolicyInsurance(policy_id=policy.id, insurance_id=i.id)  # pyright: ignore[reportArgumentType]
        for i in matched
    )
    policy.status = "ready"
    policy.chunk_strategy = strategy
    policy.detected_company = company
    session.add(policy)
    await session.commit()
