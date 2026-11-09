"""重新計算條文向量：embedding_text 改了之後，已經入庫的條文要重算才會套用。"""

import pytest
from app.core.llm import embedding_model_name, get_embeddings
from app.ingest.catalog import InsuranceSpec, ParsedRule, import_catalog
from app.ingest.reembed import reembed_rules
from app.models import Insurance, InsuranceRule, RuleEmbedding
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession


def rule(code: str, no: int, title: str, content: str) -> ParsedRule:
    return ParsedRule(
        code, no, f"條文{no}", title, content, None, f"{code}.pdf", no, no
    )


SPECS = [InsuranceSpec("T001", "甲險"), InsuranceSpec("T002", "乙險")]
RULES = [
    rule("T001", 1, "承保範圍", "被保險人於旅程中"),
    rule("T001", 2, "理賠文件", "應檢具下列文件"),
    rule("T002", 1, "承保範圍", "被保險人於旅程中"),
]


@pytest.fixture(autouse=True)
async def catalog_loaded(session: AsyncSession) -> None:
    await import_catalog(
        session, SPECS, RULES, embeddings=get_embeddings(), model=embedding_model_name()
    )


async def vector_of(
    session: AsyncSession, code: str, no: int, model: str
) -> list[float]:
    row = (
        await session.exec(
            select(RuleEmbedding)
            .join(InsuranceRule)
            .join(Insurance)
            .where(
                Insurance.code == code,
                InsuranceRule.article_no == no,
                RuleEmbedding.model == model,
            )
        )
    ).one()
    return list(row.embedding)


async def set_subsection(session: AsyncSession, code: str, no: int, value: str) -> None:
    row = (
        await session.exec(
            select(InsuranceRule)
            .join(Insurance)
            .where(Insurance.code == code, InsuranceRule.article_no == no)
        )
    ).one()
    row.subsection = value
    session.add(row)
    await session.commit()


async def test_文字變了重算向量_條文本身不動(session: AsyncSession) -> None:
    model = embedding_model_name()
    before = await vector_of(session, "T001", 2, model)
    await set_subsection(session, "T001", 2, "第二節 班機延誤保險")
    assert (
        await vector_of(session, "T001", 2, model) == before
    )  # 只改了節，向量還是舊的

    count = await reembed_rules(session, embeddings=get_embeddings(), model=model)

    assert count == 3
    assert await vector_of(session, "T001", 2, model) != before  # 節進了向量文字
    row = (
        await session.exec(
            select(InsuranceRule).where(col(InsuranceRule.article_no) == 2)
        )
    ).one()
    assert (row.title, row.content, row.subsection) == (
        "理賠文件",
        "應檢具下列文件",
        "第二節 班機延誤保險",
    )


async def test_可以只重算指定險種(session: AsyncSession) -> None:
    model = embedding_model_name()
    await set_subsection(session, "T001", 1, "第一節 旅程取消")
    await set_subsection(session, "T002", 1, "第一節 旅程取消")
    t002_before = await vector_of(session, "T002", 1, model)

    count = await reembed_rules(
        session, embeddings=get_embeddings(), model=model, insurance_codes=["T001"]
    )

    assert count == 2
    assert await vector_of(session, "T002", 1, model) == t002_before  # 沒指定的不動


async def test_其他_model_的向量不動(session: AsyncSession) -> None:
    await import_catalog(
        session,
        SPECS,
        RULES,
        embeddings=get_embeddings(),
        model="other-model",
        prune=False,
    )
    other = await vector_of(session, "T001", 1, "other-model")

    await reembed_rules(
        session, embeddings=get_embeddings(), model=embedding_model_name()
    )

    assert await vector_of(session, "T001", 1, "other-model") == other


async def test_找不到的險種直接報錯(session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="NOPE"):
        await reembed_rules(
            session,
            embeddings=get_embeddings(),
            model=embedding_model_name(),
            insurance_codes=["NOPE"],
        )


async def test_向量服務失敗時舊向量還在(session: AsyncSession) -> None:
    model = embedding_model_name()
    before = await vector_of(session, "T001", 1, model)

    class Broken:
        async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
            raise RuntimeError("provider down")

    with pytest.raises(RuntimeError):
        await reembed_rules(session, embeddings=Broken(), model=model)  # pyright: ignore[reportArgumentType]

    assert await vector_of(session, "T001", 1, model) == before
