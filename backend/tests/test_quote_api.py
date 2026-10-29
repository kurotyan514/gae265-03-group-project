import pytest
from httpx import AsyncClient

from tests.domain.golden_support import load_golden

QUOTE_CASES = {c["id"]: c for c in load_golden("pricing")["quote"]}


def body_of(case: dict) -> dict:
    return {
        "days": case["days"],
        "travelers": [
            {"age": age, "rents_car": rents_car} for age, rents_car in case["travelers"]
        ],
        **case["requirement"],
    }


@pytest.mark.parametrize(
    "case_id",
    ["q001-d1-solo30-none", "q050-d3-three-car-ill300", "q101-d30-solo30-ill2m"],
)
async def test_quote_matches_golden(client: AsyncClient, case_id: str) -> None:
    case = QUOTE_CASES[case_id]
    response = await client.post("/quote", json=body_of(case))
    assert response.status_code == 200, response.text
    assert response.json() == case["expected"]


async def test_quote_returns_plans_sorted_by_total(client: AsyncClient) -> None:
    response = await client.post(
        "/quote",
        json={"days": 5, "travelers": [{"age": 30}], "illness_medical": 300_000},
    )
    assert response.status_code == 200, response.text
    totals = [p["total"] for p in response.json()["plans"]]
    assert totals
    assert totals == sorted(totals)


async def test_quote_infectious_filter(client: AsyncClient) -> None:
    response = await client.post(
        "/quote", json={"days": 5, "travelers": [{"age": 30}], "infectious": True}
    )
    plans = response.json()["plans"]
    assert plans
    assert all(p["infectious_covered"] for p in plans)


async def test_quote_day_not_in_any_table_lists_reasons(client: AsyncClient) -> None:
    response = await client.post(
        "/quote", json={"days": 400, "travelers": [{"age": 30}]}
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["plans"] == []
    assert data["unavailable"]
    assert all(u["reason"] for u in data["unavailable"])


async def test_quote_unmet_requirement_is_unavailable(client: AsyncClient) -> None:
    response = await client.post(
        "/quote",
        json={"days": 5, "travelers": [{"age": 30}], "illness_medical": 99_000_000},
    )
    data = response.json()
    assert data["plans"] == []
    assert any("突發疾病醫療" in u["reason"] for u in data["unavailable"])


@pytest.mark.parametrize(
    "body",
    [
        {"days": 5, "travelers": [{"age": 30}] * 5},
        {"days": 5, "travelers": []},
        {"days": 5, "travelers": [{"age": 121}]},
        {"days": 5, "travelers": [{"age": -1}]},
        {"days": 0, "travelers": [{"age": 30}]},
        {"days": 5, "travelers": [{"age": 30}], "illness_medical": -1},
        {"travelers": [{"age": 30}]},
    ],
    ids=[
        "five-travelers",
        "no-travelers",
        "age-121",
        "age-negative",
        "days-zero",
        "negative-coverage",
        "no-days",
    ],
)
async def test_quote_rejects_invalid_input_with_422(
    client: AsyncClient, body: dict
) -> None:
    response = await client.post("/quote", json=body)
    assert response.status_code == 422, response.text
