"""依保額與天數查保費、下拉選項（spec #48）：查不到就是空的，不推估。"""

import pytest
from app.ingest.plan_matrix import read_plan_data
from app.seed import load_plan_data
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession


@pytest.fixture(autouse=True)
async def plan_data(session: AsyncSession) -> None:
    await load_plan_data(session, read_plan_data())


async def test_only_quoted_plans_sorted_by_premium(client: AsyncClient) -> None:
    r = await client.get("/plan-premiums", params={"sum_insured": 2_000_000, "days": 4})
    assert r.status_code == 200
    rows = r.json()
    assert [p["plan_code"] for p in rows] == [
        "taian",
        "chubb_basic",
        "tfmi_basic",
        "chubb_advanced",
        "tfmi_advanced",
    ]  # 華南、富邦沒有 200 萬的報價
    assert [p["premium"] for p in rows] == [122, 153, 343, 491, 708]
    assert rows[0]["name"] == "泰安國外旅平險"
    assert rows[0]["company"] == "泰安產物"


@pytest.mark.parametrize(("sum_insured", "days"), [(3_000_000, 3), (2_500_000, 5)])
async def test_values_not_in_the_table_have_no_quotes(
    client: AsyncClient, sum_insured: int, days: int
) -> None:
    r = await client.get(
        "/plan-premiums", params={"sum_insured": sum_insured, "days": days}
    )
    assert r.status_code == 200
    assert r.json() == []


async def test_options(client: AsyncClient) -> None:
    r = await client.get("/plan-premiums/options")
    assert r.json() == {
        "sum_insured": [n * 1_000_000 for n in range(2, 11)],
        "days": list(range(4, 11)),
    }
