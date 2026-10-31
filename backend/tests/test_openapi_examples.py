"""Swagger（/docs）上的範例：每支 API 都要有可以直接按 Try it out 的範例，而且範例本身要能通過驗證。"""

import pytest
from app.api.routes.insurances import SearchRequest
from app.api.routes.quote import QuoteRequest
from app.core.llm import embedding_model_name, get_embeddings
from app.ingest.catalog import import_catalog
from app.main import app
from httpx import AsyncClient
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

SPEC = app.openapi()
PREFIX = "/api/v1"


def request_examples(path: str) -> dict:
    content = SPEC["paths"][f"{PREFIX}{path}"]["post"]["requestBody"]["content"][
        "application/json"
    ]
    return content["examples"]


@pytest.mark.parametrize(
    ("path", "model"), [("/quote", QuoteRequest), ("/rules/search", SearchRequest)]
)
def test_post_endpoints_offer_several_named_examples_that_validate(
    path: str, model: type[BaseModel]
) -> None:
    examples = request_examples(path)
    assert len(examples) >= 3
    for name, example in examples.items():
        assert example["summary"], name
        model.model_validate(example["value"])


def test_quote_examples_cover_solo_family_and_car_rental() -> None:
    values = [e["value"] for e in request_examples("/quote").values()]
    assert any(len(v["travelers"]) == 1 for v in values)
    assert any(len(v["travelers"]) >= 3 for v in values)
    assert any(t.get("rents_car") for v in values for t in v["travelers"])


def test_search_examples_cover_every_mode_and_synonyms() -> None:
    values = [e["value"] for e in request_examples("/rules/search").values()]
    assert {"hybrid", "vector", "keyword"} <= {v.get("mode", "hybrid") for v in values}
    assert any(v.get("expand_synonyms") for v in values)
    assert any(v.get("insurance_codes") for v in values)


@pytest.mark.parametrize(
    "path", ["/insurances/{code}/rules", "/insurances/{code}/rules/{article_no}"]
)
def test_path_parameters_have_examples(path: str) -> None:
    parameters = SPEC["paths"][f"{PREFIX}{path}"]["get"]["parameters"]
    assert parameters
    assert all(p["examples"] for p in parameters if p["in"] == "path")


async def test_every_example_can_actually_be_sent(
    client: AsyncClient, session: AsyncSession, catalog
) -> None:
    """範例送出去不能是 422：用真的 16 份條款（fake embedding）載入後，把每個範例都打一次。"""
    specs, rules = catalog
    await import_catalog(
        session, specs, rules, embeddings=get_embeddings(), model=embedding_model_name()
    )
    for path in ("/quote", "/rules/search"):
        for name, example in request_examples(path).items():
            response = await client.post(path, json=example["value"])
            assert response.status_code == 200, (
                f"{path} 的範例「{name}」：{response.text}"
            )
    for path in ("/insurances/T113/rules", "/insurances/T068/rules/1"):
        assert (await client.get(path)).status_code == 200, path
