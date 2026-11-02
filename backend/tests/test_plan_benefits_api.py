"""方案保障明細與保障重點（spec #48）。"""

import pytest
from app.domain.benefits import BenefitCategory
from app.ingest.plan_matrix import read_plan_data
from app.seed import load_plan_data
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession


@pytest.fixture(autouse=True)
async def plan_data(session: AsyncSession) -> None:
    await load_plan_data(session, read_plan_data())


@pytest.mark.parametrize(
    ("plan_id", "sum_insured"), [("huanan_basic", 2_000_000), ("nope", 3_000_000)]
)
async def test_no_data_is_404(
    client: AsyncClient, plan_id: str, sum_insured: int
) -> None:
    r = await client.get(
        f"/plans/{plan_id}/benefits", params={"sum_insured": sum_insured}
    )
    assert r.status_code == 404


async def test_details_and_highlights_in_category_order(client: AsyncClient) -> None:
    r = await client.get(
        "/plans/huanan_basic/benefits", params={"sum_insured": 3_000_000}
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["benefits"]) == 18
    assert body["benefits"][0] == {
        "name": "身故失能保險金",
        "category": None,
        "amount": 3_000_000,
    }
    categories = [h["category"] for h in body["highlights"]]
    assert categories == [c for c in BenefitCategory if c in categories]
    assert all(
        b["category"] == h["category"]
        for h in body["highlights"]
        for b in h["benefits"]
    )
    flight = next(h for h in body["highlights"] if h["category"] == "班機延誤")
    assert flight["benefits"][0]["amount"] == 6000


async def test_fubon_after_return_inpatient_is_under_illness_inpatient(
    client: AsyncClient,
) -> None:
    r = await client.get(
        "/plans/fubon_basic/benefits", params={"sum_insured": 6_000_000}
    )
    inpatient = next(
        h for h in r.json()["highlights"] if h["category"] == "海外疾病住院"
    )
    assert "海外突發疾病返國後住院醫療" in [b["name"] for b in inpatient["benefits"]]
