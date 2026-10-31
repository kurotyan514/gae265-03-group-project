"""匯入條文與向量到資料庫（測試一律用 fake embedding）。"""

import pytest
from app.core.config import settings
from app.core.llm import get_embeddings
from app.ingest.catalog import ImportResult, InsuranceSpec, ParsedRule, import_catalog
from app.models import Insurance, InsuranceRule, RuleEmbedding
from sqlalchemy import func
from sqlalchemy import select as sa_select
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

MODEL = "fake"


def rule(code: str, no: int, content: str = "內文") -> ParsedRule:
    return ParsedRule(
        code, no, f"條文{no}", f"標題{no}", content, None, f"{code}.pdf", no, no
    )


SPECS = [InsuranceSpec("T001", "甲險"), InsuranceSpec("T002", "乙險")]
RULES = [rule("T001", 1), rule("T001", 2), rule("T002", 1)]


async def count(session: AsyncSession, table) -> int:
    return await session.scalar(sa_select(func.count()).select_from(table)) or 0


async def test_import_real_catalog_counts(session: AsyncSession, catalog) -> None:
    specs, rules = catalog
    result = await import_catalog(
        session, specs, rules, embeddings=get_embeddings(), model=MODEL
    )
    assert result == ImportResult(insurances=17, rules=300, embeddings=300)
    assert [
        await count(session, t) for t in (Insurance, InsuranceRule, RuleEmbedding)
    ] == [17, 300, 300]


async def test_embeddings_have_configured_dimensions(session: AsyncSession) -> None:
    await import_catalog(
        session, SPECS, RULES, embeddings=get_embeddings(), model=MODEL
    )
    vectors = (await session.exec(select(RuleEmbedding.embedding))).all()
    assert len(vectors) == 3
    assert {len(v) for v in vectors} == {settings.EMBEDDING_DIMENSIONS}


async def test_reimport_keeps_ids_and_does_not_duplicate(session: AsyncSession) -> None:
    emb = get_embeddings()
    await import_catalog(session, SPECS, RULES, embeddings=emb, model=MODEL)
    ids = set((await session.exec(select(Insurance.id))).all()) | set(
        (await session.exec(select(InsuranceRule.id))).all()
    )

    await import_catalog(session, SPECS, RULES, embeddings=emb, model=MODEL)
    ids_again = set((await session.exec(select(Insurance.id))).all()) | set(
        (await session.exec(select(InsuranceRule.id))).all()
    )
    assert ids == ids_again  # 其他資料表可能用 UUID 指到險種，重匯不可以換 id
    assert [
        await count(session, t) for t in (Insurance, InsuranceRule, RuleEmbedding)
    ] == [2, 3, 3]


async def test_reimport_updates_changed_content_and_drops_removed_articles(
    session: AsyncSession,
) -> None:
    emb = get_embeddings()
    await import_catalog(session, SPECS, RULES, embeddings=emb, model=MODEL)

    changed = [rule("T001", 1, "改過的內文"), rule("T002", 1)]  # T001 第 2 條被拿掉
    result = await import_catalog(session, SPECS, changed, embeddings=emb, model=MODEL)

    assert result.rules == 2
    contents = {
        (r.article_no, r.content)
        for r in (await session.exec(select(InsuranceRule))).all()
    }
    assert (1, "改過的內文") in contents
    assert [await count(session, t) for t in (InsuranceRule, RuleEmbedding)] == [2, 2]


async def test_embeddings_of_other_models_are_left_alone(session: AsyncSession) -> None:
    emb = get_embeddings()
    await import_catalog(session, SPECS, RULES, embeddings=emb, model="old-model")
    await import_catalog(session, SPECS, RULES, embeddings=emb, model=MODEL)
    assert await count(session, RuleEmbedding) == 6


async def test_rule_for_unknown_insurance_fails(session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="T999"):
        await import_catalog(
            session, SPECS, [rule("T999", 1)], embeddings=get_embeddings(), model=MODEL
        )
