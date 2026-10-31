"""險種、條文、條文向量三張表：唯一性限制與連動刪除。"""

import pytest
from app.core.config import settings
from app.models import Insurance, InsuranceRule, RuleEmbedding
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, func
from sqlmodel import select as sm_select
from sqlmodel.ext.asyncio.session import AsyncSession

MODEL = "text-embedding-3-large"


def vector(value: float = 0.1) -> list[float]:
    return [value] * settings.EMBEDDING_DIMENSIONS


def rule(insurance: Insurance, article_no: int = 1, **kw) -> InsuranceRule:
    return InsuranceRule(
        insurance_id=insurance.id,
        article_no=article_no,
        chapter="條文一",
        title="名詞定義",
        content="本保險契約所稱…",
        source_file="T068.pdf",
        page_start=1,
        page_end=1,
        **kw,
    )


async def add_insurance(
    session: AsyncSession, code: str = "T068", name: str = "旅行平安保險"
) -> Insurance:
    insurance = Insurance(code=code, name=name)
    session.add(insurance)
    await session.commit()
    return insurance


async def test_default_embedding_dimensions_is_1024() -> None:
    assert settings.EMBEDDING_DIMENSIONS == 1024


async def test_insurance_code_and_name_are_unique(session: AsyncSession) -> None:
    await add_insurance(session)
    session.add(Insurance(code="T068", name="別的名稱"))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()
    session.add(Insurance(code="T999", name="旅行平安保險"))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_article_number_is_unique_within_an_insurance(
    session: AsyncSession,
) -> None:
    first = await add_insurance(session)
    other = await add_insurance(session, "T070", "傷害醫療費用保險")
    session.add_all(
        [rule(first, 1), rule(other, 1), rule(first, 2)]
    )  # 不同險種可以有同一個條號
    await session.commit()

    session.add(rule(first, 1))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_section_is_optional(session: AsyncSession) -> None:
    insurance = await add_insurance(session)
    session.add(rule(insurance, 1))
    session.add(rule(insurance, 2, section="第二章 旅程取消保險"))
    await session.commit()
    rows = (
        await session.exec(
            sm_select(InsuranceRule).order_by(col(InsuranceRule.article_no))
        )
    ).all()
    sections = [r.section for r in rows]
    assert sections == [None, "第二章 旅程取消保險"]


async def test_one_embedding_per_rule_and_model(session: AsyncSession) -> None:
    insurance = await add_insurance(session)
    a_rule = rule(insurance)
    session.add(a_rule)
    await session.commit()

    session.add(RuleEmbedding(rule_id=a_rule.id, model=MODEL, embedding=vector()))
    session.add(
        RuleEmbedding(rule_id=a_rule.id, model="bge-m3", embedding=vector(0.2))
    )  # 不同模型可以並存
    await session.commit()

    session.add(RuleEmbedding(rule_id=a_rule.id, model=MODEL, embedding=vector(0.3)))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_embedding_dimension_is_enforced(session: AsyncSession) -> None:
    insurance = await add_insurance(session)
    a_rule = rule(insurance)
    session.add(a_rule)
    await session.commit()

    session.add(
        RuleEmbedding(rule_id=a_rule.id, model=MODEL, embedding=[0.1, 0.2, 0.3])
    )
    with pytest.raises(Exception, match="dimension"):
        await session.commit()


async def test_deleting_an_insurance_removes_its_rules_and_embeddings(
    session: AsyncSession,
) -> None:
    insurance = await add_insurance(session)
    a_rule = rule(insurance)
    session.add(a_rule)
    await session.commit()
    session.add(RuleEmbedding(rule_id=a_rule.id, model=MODEL, embedding=vector()))
    await session.commit()

    await session.delete(insurance)
    await session.commit()

    for table in (Insurance, InsuranceRule, RuleEmbedding):
        assert await session.scalar(select(func.count()).select_from(table)) == 0
