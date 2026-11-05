"""依保額與天數查保費、下拉選項（spec #48）：查不到就是空的，不推估。"""

import pytest
from app.domain.benefits import CONCERN_BENEFITS
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


def test_every_concern_benefit_exists_in_seed() -> None:
    names = {b["name"] for b in read_plan_data()["benefits"]}
    for concern, benefits in CONCERN_BENEFITS.items():
        assert benefits <= names, (concern, benefits - names)


async def concern_amounts(client: AsyncClient, concerns: str) -> dict[str, dict]:
    r = await client.get(
        "/plan-premiums",
        params={"sum_insured": 3_000_000, "days": 5, "concerns": concerns},
    )
    assert r.status_code == 200
    return {p["plan_code"]: p["concern_amounts"] for p in r.json()}


async def test_flight_delay_amounts(client: AsyncClient) -> None:
    amounts = await concern_amounts(client, "班機延誤")
    assert amounts["taian"] == {"班機延誤": 0}
    assert amounts["huanan_basic"] == {"班機延誤": 6000}


async def test_trip_cancellation_sums_cancel_and_change(client: AsyncClient) -> None:
    amounts = await concern_amounts(client, "行程取消或縮短")
    assert amounts["chubb_advanced"] == {"行程取消或縮短": 320_000}
    assert amounts["tfmi_basic"] == {"行程取消或縮短": 40_000}
    assert amounts["huanan_basic"] == {"行程取消或縮短": 50_000}  # 沒有法定傳染病
    assert amounts["taian"] == {"行程取消或縮短": 0}


async def test_medical_includes_accident_and_illness(client: AsyncClient) -> None:
    amounts = await concern_amounts(client, "生病或受傷就醫,證件遺失")
    # 傷害醫療 30 萬 + 疾病住院／急診／門診
    assert amounts["taian"]["生病或受傷就醫"] == 300_000 + 90_000 + 900 + 900
    assert amounts["tfmi_basic"]["生病或受傷就醫"] == 300_000 + 300_000 + 15_000 + 6_000
    assert set(amounts["taian"]) == {"生病或受傷就醫", "證件遺失"}


async def test_unknown_concern_is_422(client: AsyncClient) -> None:
    r = await client.get(
        "/plan-premiums",
        params={"sum_insured": 3_000_000, "days": 5, "concerns": "班機延誤,颱風"},
    )
    assert r.status_code == 422
    assert "颱風" in r.json()["detail"]


async def test_lost_items_is_no_longer_a_concern(client: AsyncClient) -> None:
    r = await client.get(
        "/plan-premiums",
        params={"sum_insured": 3_000_000, "days": 5, "concerns": "東西弄丟"},
    )
    assert r.status_code == 422
    assert r.json()["detail"] == (
        "不認得的在意事項：東西弄丟（可選：班機延誤, 行程取消或縮短, 行李延誤, "
        "行李遺失或損壞, 生病或受傷就醫, 證件遺失, 信用卡盜刷）"
    )


async def test_without_concerns_there_is_no_concern_amounts(
    client: AsyncClient,
) -> None:
    r = await client.get("/plan-premiums", params={"sum_insured": 3_000_000, "days": 5})
    assert all("concern_amounts" not in p for p in r.json())
