import pytest
from app.core.llm import embedding_model_name, get_embeddings
from app.domain.rag.hybrid import MAX_K, rrf_merge, search_rules
from app.ingest.catalog import (
    ImportResult,
    InsuranceSpec,
    ParsedRule,
    embedding_text,
    import_catalog,
)
from sqlmodel.ext.asyncio.session import AsyncSession

from tests.domain.golden_support import load_golden

RAG = load_golden("rag")


# ---- RRF ----


def test_rrf_merges_by_rank():
    merged = rrf_merge([["a", "b", "c"], ["b", "a", "d"]])
    ids = [i for i, _ in merged]
    assert set(ids[:2]) == {"a", "b"}
    assert set(ids[2:]) == {"c", "d"}


def test_rrf_one_empty_ranking():
    assert [i for i, _ in rrf_merge([["a", "b"], []])] == ["a", "b"]


def test_rrf_item_in_both_beats_item_in_one():
    merged = dict(rrf_merge([["a", "x"], ["a", "y"]]))
    assert merged["a"] > merged["x"]
    assert merged["a"] > merged["y"]


@pytest.mark.parametrize("case", RAG["rrf"], ids=range(len(RAG["rrf"])))
def test_rrf_matches_golden(case):
    merged = (
        rrf_merge(case["rankings"])
        if case["k"] is None
        else rrf_merge(case["rankings"], k=case["k"])
    )
    assert [i for i, _ in merged] == [i for i, _ in case["expected"]]
    assert [s for _, s in merged] == pytest.approx([s for _, s in case["expected"]])


# ---- 檢索（fake embedding；向量排名無語意，只測流程與篩選） ----


def rule(code: str, no: int, title: str, content: str) -> ParsedRule:
    return ParsedRule(
        code, no, f"條文{no}", title, content, "第一章", f"{code}.pdf", no + 2, no + 2
    )


SPECS = [InsuranceSpec("T001", "甲險"), InsuranceSpec("T002", "乙險")]
RULES = [
    rule("T001", 1, "承保範圍", "被保險人於滑雪場發生意外事故，本公司給付保險金"),
    rule(
        "T001",
        2,
        "除外責任",
        "被保險人從事競賽或表演活動所致之傷害，本公司不負給付責任",
    ),
    rule("T002", 1, "班機延誤", "搭乘之班機延誤超過六小時，本公司給付延誤費用"),
    rule("T002", 2, "行李延誤", "託運行李延誤超過六小時，本公司給付必要之日用品費用"),
]


@pytest.fixture
async def loaded(session: AsyncSession) -> ImportResult:
    return await import_catalog(
        session, SPECS, RULES, embeddings=get_embeddings(), model=embedding_model_name()
    )


@pytest.mark.usefixtures("loaded")
async def test_keyword_mode_finds_the_exact_term(session: AsyncSession) -> None:
    hits = await search_rules(session, "滑雪場", mode="keyword")
    assert [(h.insurance_code, h.article_no) for h in hits] == [("T001", 1)]
    assert hits[0].sources == ["keyword"]
    assert hits[0].similarity is None


@pytest.mark.usefixtures("loaded")
async def test_vector_mode_ranks_identical_text_first(session: AsyncSession) -> None:
    query = embedding_text("乙險", RULES[2])  # 與條文的向量文字完全相同 → 相似度 1
    hits = await search_rules(session, query, mode="vector", k=4)
    assert (hits[0].insurance_code, hits[0].article_no) == ("T002", 1)
    assert hits[0].similarity == pytest.approx(1.0)
    assert all(h.sources == ["vector"] for h in hits)


@pytest.mark.usefixtures("loaded")
async def test_hybrid_combines_both_routes_and_returns_original_text(
    session: AsyncSession,
) -> None:
    query = embedding_text("乙險", RULES[2])
    hits = await search_rules(session, query, k=3)
    top = hits[0]
    assert (top.insurance_code, top.article_no) == ("T002", 1)
    assert set(top.sources) == {"vector", "keyword"}
    assert top.content == RULES[2].content  # 原文不經 LLM
    assert (top.insurance_name, top.title, top.source_file, top.page_start) == (
        "乙險",
        "班機延誤",
        "T002.pdf",
        3,
    )
    assert top.score > hits[1].score


@pytest.mark.usefixtures("loaded")
async def test_filter_by_insurance_codes(session: AsyncSession) -> None:
    hits = await search_rules(
        session, "班機延誤 滑雪場", k=10, insurance_codes=["T001"]
    )
    assert {h.insurance_code for h in hits} == {"T001"}
    both = await search_rules(session, "延誤", k=10, insurance_codes=["T001", "T002"])
    assert {h.insurance_code for h in both} == {"T001", "T002"}


@pytest.mark.usefixtures("loaded")
async def test_k_limits_the_result_count(session: AsyncSession) -> None:
    assert len(await search_rules(session, "本公司給付", k=2)) == 2
    assert len(await search_rules(session, "本公司給付", k=1)) == 1


@pytest.mark.parametrize("query", ["", "   ", "，。！"])
@pytest.mark.usefixtures("loaded")
async def test_empty_query_raises(session: AsyncSession, query: str) -> None:
    with pytest.raises(ValueError, match="不可為空"):
        await search_rules(session, query)


@pytest.mark.usefixtures("loaded")
async def test_unknown_insurance_code_lists_choices(session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="T999") as e:
        await search_rules(session, "滑雪", insurance_codes=["T999"])
    assert "T001" in str(e.value) and "T002" in str(e.value)


@pytest.mark.parametrize("k", [0, -1, MAX_K + 1])
@pytest.mark.usefixtures("loaded")
async def test_k_out_of_range_raises(session: AsyncSession, k: int) -> None:
    with pytest.raises(ValueError, match="k"):
        await search_rules(session, "滑雪", k=k)


@pytest.mark.usefixtures("loaded")
async def test_unknown_mode_raises(session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="mode"):
        await search_rules(session, "滑雪", mode="semantic")  # pyright: ignore[reportArgumentType]


async def test_only_vectors_of_the_configured_model_are_searched(
    session: AsyncSession,
) -> None:
    await import_catalog(
        session, SPECS, RULES, embeddings=get_embeddings(), model="some-other-model"
    )
    assert await search_rules(session, "滑雪場", mode="vector") == []


@pytest.mark.usefixtures("loaded")
async def test_index_is_rebuilt_after_reimport(session: AsyncSession) -> None:
    assert await search_rules(session, "跳傘", mode="keyword") == []
    changed = [*RULES, rule("T001", 3, "跳傘", "被保險人從事跳傘活動所致之傷害")]
    await import_catalog(
        session,
        SPECS,
        changed,
        embeddings=get_embeddings(),
        model=embedding_model_name(),
    )
    hits = await search_rules(session, "跳傘", mode="keyword")
    assert [(h.insurance_code, h.article_no) for h in hits] == [("T001", 3)]


async def test_synonym_expansion_bridges_colloquial_wording(
    session: AsyncSession,
) -> None:
    stolen = [
        rule("T001", 1, "承保範圍", "被保險人之行動電話遭竊盜、強盜或搶奪所致之損失")
    ]
    await import_catalog(
        session,
        SPECS[:1],
        stolen,
        embeddings=get_embeddings(),
        model=embedding_model_name(),
    )
    assert (
        await search_rules(session, "手機被偷", mode="keyword") == []
    )  # 口語和條文用詞對不上
    hits = await search_rules(session, "手機被偷", mode="keyword", expand_synonyms=True)
    assert [(h.insurance_code, h.article_no) for h in hits] == [("T001", 1)]
