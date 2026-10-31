import pytest
from app.core.llm import embedding_model_name, get_embeddings
from app.domain.rag.hybrid import MAX_K
from app.ingest.catalog import InsuranceSpec, ParsedRule, import_catalog
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession


def rule(
    code: str, no: int, title: str, content: str, section: str | None = "第一章"
) -> ParsedRule:
    return ParsedRule(
        code, no, f"條文{no}", title, content, section, f"{code}.pdf", no + 2, no + 3
    )


SPECS = [InsuranceSpec("T001", "甲險"), InsuranceSpec("T002", "乙險")]
RULES = [
    rule("T001", 25, "承保範圍", "被保險人於滑雪場發生意外事故，本公司給付保險金"),
    rule("T001", 1, "名詞定義", "本保險契約所稱被保險人", section=None),
    rule("T002", 1, "班機延誤", "搭乘之班機延誤超過六小時，本公司給付延誤費用"),
]


@pytest.fixture(autouse=True)
async def catalog_loaded(session: AsyncSession) -> None:
    await import_catalog(
        session, SPECS, RULES, embeddings=get_embeddings(), model=embedding_model_name()
    )


async def test_list_insurances_with_rule_counts(client: AsyncClient) -> None:
    response = await client.get("/insurances")
    assert response.status_code == 200, response.text
    assert response.json() == [
        {"code": "T001", "name": "甲險", "rule_count": 2},
        {"code": "T002", "name": "乙險", "rule_count": 1},
    ]


async def test_list_rules_of_an_insurance_in_article_order(client: AsyncClient) -> None:
    response = await client.get("/insurances/T001/rules")
    assert response.status_code == 200, response.text
    rules = response.json()
    assert [r["article_no"] for r in rules] == [1, 25]  # 條號會跳號
    assert rules[1] == {
        "insurance_code": "T001",
        "insurance_name": "甲險",
        "article_no": 25,
        "chapter": "條文25",
        "title": "承保範圍",
        "content": "被保險人於滑雪場發生意外事故，本公司給付保險金",
        "section": "第一章",
        "source_file": "T001.pdf",
        "page_start": 27,
        "page_end": 28,
    }
    assert rules[0]["section"] is None


async def test_get_a_single_rule(client: AsyncClient) -> None:
    response = await client.get("/insurances/T002/rules/1")
    assert response.status_code == 200, response.text
    assert response.json()["title"] == "班機延誤"


@pytest.mark.parametrize(
    "path",
    ["/insurances/T999/rules", "/insurances/T999/rules/1", "/insurances/T001/rules/2"],
)
async def test_unknown_insurance_or_article_is_404(
    client: AsyncClient, path: str
) -> None:
    response = await client.get(path)
    assert response.status_code == 404
    assert response.json()["detail"]


async def test_search_returns_original_text_with_citation(client: AsyncClient) -> None:
    response = await client.post(
        "/rules/search", json={"query": "滑雪場", "mode": "keyword"}
    )
    assert response.status_code == 200, response.text
    [hit] = response.json()
    assert hit["insurance_code"] == "T001" and hit["article_no"] == 25
    assert hit["content"] == RULES[0].content  # 原文，不經 LLM
    assert hit["citation"] == "甲險 條文25 承保範圍（T001.pdf 第 27 頁）"
    assert (
        hit["sources"] == ["keyword"] and hit["similarity"] is None and hit["score"] > 0
    )


async def test_search_defaults_to_hybrid_and_filters_by_insurance(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/rules/search", json={"query": "延誤 滑雪場", "insurance_codes": ["T002"]}
    )
    assert response.status_code == 200, response.text
    hits = response.json()
    assert hits and {h["insurance_code"] for h in hits} == {"T002"}
    assert all(set(h["sources"]) <= {"vector", "keyword"} for h in hits)


async def test_search_k_limits_results(client: AsyncClient) -> None:
    response = await client.post("/rules/search", json={"query": "本公司給付", "k": 1})
    assert len(response.json()) == 1


@pytest.mark.parametrize(
    "body",
    [
        {"query": ""},
        {"query": "，。！"},
        {"query": "滑雪", "k": 0},
        {"query": "滑雪", "k": MAX_K + 1},
        {"query": "滑雪", "mode": "semantic"},
        {"query": "滑雪", "insurance_codes": ["T999"]},
        {},
    ],
    ids=[
        "empty",
        "punctuation-only",
        "k-zero",
        "k-too-big",
        "bad-mode",
        "unknown-insurance",
        "no-query",
    ],
)
async def test_search_rejects_invalid_input_with_422(
    client: AsyncClient, body: dict
) -> None:
    response = await client.post("/rules/search", json=body)
    assert response.status_code == 422, response.text


async def test_search_can_expand_synonyms(client: AsyncClient) -> None:
    body = {"query": "飛機誤點", "mode": "keyword"}
    assert (
        await client.post("/rules/search", json=body)
    ).json() == []  # 條文寫的是「延誤」
    response = await client.post(
        "/rules/search", json={**body, "expand_synonyms": True}
    )
    assert response.status_code == 200, response.text
    assert [h["insurance_code"] for h in response.json()] == ["T002"]
