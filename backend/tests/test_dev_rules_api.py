"""GET /rules：列出資料庫裡全部條文（含向量狀態），給開發用的測試網頁和核對匯入用。只在非 production 註冊。"""

import pytest
from app.api.main import build_api_router
from app.core.llm import embedding_model_name, get_embeddings
from app.ingest.catalog import InsuranceSpec, ParsedRule, import_catalog
from fastapi import FastAPI
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession


def rule(code: str, no: int, title: str, content: str) -> ParsedRule:
    return ParsedRule(
        code, no, f"條文{no}", title, content, None, f"{code}.pdf", no, no
    )


SPECS = [InsuranceSpec("T001", "甲險"), InsuranceSpec("T002", "乙險")]
RULES = [
    rule("T001", 1, "名詞定義", "本保險契約所稱被保險人"),
    rule("T001", 25, "承保範圍", "被保險人於滑雪場發生意外事故"),
    rule("T002", 1, "班機延誤", "搭乘之班機延誤超過六小時"),
]


@pytest.fixture(autouse=True)
async def catalog_loaded(session: AsyncSession) -> None:
    await import_catalog(
        session, SPECS, RULES, embeddings=get_embeddings(), model=embedding_model_name()
    )
    # 再用另一個 model 匯入 T002，讓「向量狀態」有不同的值可以看
    await import_catalog(
        session, SPECS[1:], RULES[2:], embeddings=get_embeddings(), model="other-model"
    )


async def test_lists_every_rule_with_total_and_vector_status(
    client: AsyncClient,
) -> None:
    response = await client.get("/rules")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total"] == 3
    assert [(r["insurance_code"], r["article_no"]) for r in data["items"]] == [
        ("T001", 1),
        ("T001", 25),
        ("T002", 1),
    ]
    first = data["items"][0]
    assert first["content"] == "本保險契約所稱被保險人"
    assert first["embedding_models"] == [embedding_model_name()]
    assert first["embedding_dimensions"] == 1024
    assert sorted(data["items"][2]["embedding_models"]) == sorted(
        [embedding_model_name(), "other-model"]
    )


async def test_filter_by_insurance_and_text(client: AsyncClient) -> None:
    by_code = (await client.get("/rules", params={"insurance_code": "T001"})).json()
    assert by_code["total"] == 2
    by_text = (await client.get("/rules", params={"q": "滑雪"})).json()
    assert [r["article_no"] for r in by_text["items"]] == [25]
    by_title = (await client.get("/rules", params={"q": "班機"})).json()
    assert [r["insurance_code"] for r in by_title["items"]] == ["T002"]


async def test_pagination_keeps_the_total(client: AsyncClient) -> None:
    page = (await client.get("/rules", params={"limit": 2, "offset": 1})).json()
    assert page["total"] == 3
    assert [(r["insurance_code"], r["article_no"]) for r in page["items"]] == [
        ("T001", 25),
        ("T002", 1),
    ]


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 501}, {"offset": -1}])
async def test_invalid_paging_is_422(client: AsyncClient, params: dict) -> None:
    assert (await client.get("/rules", params=params)).status_code == 422


def paths(environment: str) -> set[str]:
    app = FastAPI()
    app.include_router(build_api_router(environment))
    return set(app.openapi()["paths"])


def test_rules_listing_is_not_registered_in_production() -> None:
    assert "/rules" in paths("local")
    assert "/rules" in paths("test")
    assert "/rules" not in paths("production")
    assert {"/health", "/quote", "/rules/search"} <= paths("production")
