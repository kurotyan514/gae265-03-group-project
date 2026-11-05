"""1-4 情境試算（spec #120）：GET /comparisons/{id}/scenarios，數字全由程式依 plan_benefit 與給付規則算出。"""

from collections.abc import AsyncGenerator, Iterator
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from app.api.deps import current_user
from app.domain.scenarios import PayoutRule, load_scenario_rules
from app.ingest.plan_matrix import read_plan_data
from app.main import app
from app.models import User
from app.seed import SEED_PATH, load_plan_data, load_seed, read_seed
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

TODAY = datetime.now(ZoneInfo("Asia/Taipei")).date()
FLIGHT = "班機延誤保險(定額給付-累進式)"


def trip(days: int, concerns: list[str]) -> dict:
    depart = TODAY + timedelta(days=1)
    return {
        "destination": "日本",
        "depart_date": depart.isoformat(),
        "return_date": (depart + timedelta(days=days - 1)).isoformat(),
        "age": 30,
        "concerns": concerns,
    }


@pytest.fixture
async def user(session: AsyncSession) -> AsyncGenerator[User]:
    u = User(email="a@example.com")
    session.add(u)
    await session.commit()
    app.dependency_overrides[current_user] = lambda: u
    yield u
    app.dependency_overrides.pop(current_user, None)


@pytest.fixture
def rules() -> Iterator[dict[str, dict[str, PayoutRule]]]:
    """測試自己的給付規則（不讀 scenario_rules.json）；測試直接改這個 dict。"""
    r: dict[str, dict[str, PayoutRule]] = {}
    app.dependency_overrides[load_scenario_rules] = lambda: r
    yield r
    app.dependency_overrides.pop(load_scenario_rules, None)


def tiny_plan_data() -> dict:
    """兩個方案、5 天。泰安：班機延誤 6,000、行李損失 2,000，傷害醫療隨身故保額變；
    安達基礎型：班機延誤 3,000，沒有行李損失。行李延誤同額，所以在意班機延誤時推薦泰安。"""
    plans = {
        "taian": {
            2_000_000: (100, {FLIGHT: 6000, "行李損失保險(定額給付)": 2000}),
            3_000_000: (150, {FLIGHT: 6000, "行李損失保險(定額給付)": 2000}),
        },
        "chubb_basic": {2_000_000: (200, {FLIGHT: 3000})},
    }
    category = {
        FLIGHT: "班機延誤",
        "行李延誤保險(定額給付)": "行李延誤",
        "行李損失保險(定額給付)": "行李損失",
        "傷害醫療費用保險": "意外醫療",
    }
    premiums, benefits = [], []
    for code, sums in plans.items():
        for sum_insured, (premium, extra) in sums.items():
            premiums.append(
                {
                    "plan_code": code,
                    "sum_insured": sum_insured,
                    "days": 5,
                    "premium": premium,
                }
            )
            items = {
                "身故失能保險金": sum_insured,
                "行李延誤保險(定額給付)": 500,
                "傷害醫療費用保險": sum_insured // 10,
            } | extra
            benefits += [
                {
                    "plan_code": code,
                    "sum_insured": sum_insured,
                    "name": name,
                    "category": category.get(name),
                    "amount": amount,
                    "position": i,
                }
                for i, (name, amount) in enumerate(items.items())
            ]
    return {"premiums": premiums, "benefits": benefits}


@pytest.fixture
async def tiny(session: AsyncSession) -> None:
    await load_plan_data(session, tiny_plan_data())


async def create(client: AsyncClient, days: int, concerns: list[str]) -> str:
    r = await client.post("/comparisons", json=trip(days, concerns))
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def scenarios(client: AsyncClient, comparison_id: str) -> list[dict]:
    r = await client.get(f"/comparisons/{comparison_id}/scenarios")
    assert r.status_code == 200, r.text
    return r.json()


def tab(body: list[dict], concern: str) -> dict:
    return next(s for s in body if s["concern"] == concern)


@pytest.mark.usefixtures("user", "tiny", "rules")
async def test_tabs_put_concerns_first_then_fill_to_five(client: AsyncClient) -> None:
    body = await scenarios(client, await create(client, 5, ["行李延誤", "班機延誤"]))
    assert [(s["concern"], s["starred"]) for s in body] == [
        ("行李延誤", True),
        ("班機延誤", True),
        ("行程取消或縮短", False),
        ("行李遺失或損壞", False),
        ("生病或受傷就醫", False),
    ]
    flight = tab(body, "班機延誤")
    assert flight["story"] == "颱風來了，回程班機延誤 8 小時，你在機場一路等到半夜。"
    assert flight["assumption"] == "延誤 8 小時"
    # 欄是清單：推薦在前、次推薦在後
    assert [(p["plan_code"], p["recommended"]) for p in flight["plans"]] == [
        ("taian", True),
        ("chubb_basic", False),
    ]


@pytest.mark.usefixtures("user", "tiny", "rules")
async def test_other_users_comparison_is_404_and_no_recommendation_is_422(
    client: AsyncClient, session: AsyncSession
) -> None:
    mine = await create(client, 5, ["班機延誤"])
    empty = await create(client, 5, [])
    r = await client.get(f"/comparisons/{empty}/scenarios")
    assert r.status_code == 422

    other = User(email="b@example.com")
    session.add(other)
    await session.commit()
    app.dependency_overrides[current_user] = lambda: other
    r = await client.get(f"/comparisons/{mine}/scenarios")
    assert r.status_code == 404


def col_of(body: list[dict], concern: str, plan_code: str) -> dict:
    return next(p for p in tab(body, concern)["plans"] if p["plan_code"] == plan_code)


@pytest.mark.usefixtures("user", "tiny")
async def test_fixed_payout_follows_rule_and_cap(
    client: AsyncClient, rules: dict[str, dict[str, PayoutRule]]
) -> None:
    cid = await create(client, 5, ["班機延誤"])
    # 8 小時、起賠 4、每滿 4 小時 2,000：泰安上限 6,000 → 4,000；安達上限 3,000 → 3,000
    rules["taian"] = {FLIGHT: PayoutRule(4, 4, 2000)}
    rules["chubb_basic"] = {FLIGHT: PayoutRule(4, 4, 2000)}
    flight = tab(await scenarios(client, cid), "班機延誤")
    assert flight["conclusion"] == (
        "延誤 8 小時：泰安國外旅平險 賠 4,000 元；安達國外旅平險-基礎型 賠 3,000 元。"
    )
    taian, chubb = flight["plans"]
    assert taian | {"basis": None} == {
        "plan_code": "taian",
        "name": "泰安國外旅平險",
        "company": "泰安產物",
        "recommended": True,
        "result": "在保障範圍內",
        "benefit": FLIGHT,
        "benefit_explanation": taian["benefit_explanation"],
        "method": "定額",
        "method_explanation": taian["method_explanation"],
        "how": "延誤滿 4 小時起賠，每滿 4 小時賠 2,000 元",
        "max_amount": 6000,
        "payout": 4000,
        "outcome": "4,000 元",
        "basis": None,
    }
    assert taian["benefit_explanation"] and taian["method_explanation"]
    assert (chubb["payout"], chubb["max_amount"]) == (3000, 3000)

    # 起賠 10 小時：0 元、未達給付條件
    rules["taian"] = {FLIGHT: PayoutRule(10, 4, 2000)}
    taian = col_of(await scenarios(client, cid), "班機延誤", "taian")
    assert (taian["result"], taian["payout"], taian["outcome"]) == (
        "在保障範圍內，但本情境未達給付條件",
        0,
        "0 元",
    )


@pytest.mark.usefixtures("user", "tiny", "rules")
async def test_fixed_without_rule_shows_only_the_cap(client: AsyncClient) -> None:
    body = await scenarios(client, await create(client, 5, ["班機延誤"]))
    flight = tab(body, "班機延誤")
    assert flight["conclusion"] == (
        "延誤 8 小時：泰安國外旅平險 依延誤時數計算，最高 6,000 元；"
        "安達國外旅平險-基礎型 依延誤時數計算，最高 3,000 元。"
    )
    chubb = flight["plans"][1]
    assert (chubb["result"], chubb["payout"], chubb["outcome"]) == (
        "在保障範圍內",
        None,
        "依延誤時數計算，最高 3,000 元",
    )


@pytest.mark.usefixtures("user", "tiny", "rules")
async def test_not_listed_and_reimbursement(client: AsyncClient) -> None:
    body = await scenarios(client, await create(client, 5, ["班機延誤"]))
    loss = tab(body, "行李遺失或損壞")
    assert loss["conclusion"] == (
        "泰安國外旅平險 依實際收據，最高 2,000 元；安達國外旅平險-基礎型 試算表未列，請查條款。"
    )
    taian, chubb = loss["plans"]
    assert (taian["method"], taian["outcome"], taian["method_explanation"]) == (
        "依實際損失",
        "依實際收據，最高 2,000 元",
        None,
    )
    assert chubb["result"] == "試算表未列，請查條款"
    rest = {
        k: v
        for k, v in chubb.items()
        if k not in {"plan_code", "name", "company", "recommended", "result"}
    }
    assert set(rest.values()) == {None}

    medical = col_of(body, "生病或受傷就醫", "taian")
    assert (medical["method"], medical["outcome"], medical["max_amount"]) == (
        "實支實付",
        "依實際收據，最高 200,000 元",
        200_000,
    )
    assert medical["method_explanation"]


@pytest.mark.usefixtures("user", "tiny", "rules")
async def test_max_amount_follows_card_sum_insured(client: AsyncClient) -> None:
    cid = await create(client, 5, ["班機延誤"])
    r = await client.patch(
        f"/comparisons/{cid}", json={"recommended_sum_insured": 3_000_000}
    )
    assert r.status_code == 200, r.text
    medical = col_of(await scenarios(client, cid), "生病或受傷就醫", "taian")
    assert (medical["max_amount"], medical["outcome"]) == (
        300_000,
        "依實際收據，最高 300,000 元",
    )


@pytest.mark.usefixtures("user", "rules")
async def test_basis_points_to_smallest_article_of_matching_chapter(
    client: AsyncClient, session: AsyncSession
) -> None:
    await load_plan_data(session, read_plan_data())
    # 條文與險種用真實 seed；向量用不到，不載入
    await load_seed(session, read_seed(SEED_PATH) | {"embeddings": []})
    # 6 天、在意班機延誤：推薦富邦進階型
    body = await scenarios(
        client, await create(client, 6, ["班機延誤", "生病或受傷就醫"])
    )
    fubon = col_of(body, "班機延誤", "fubon_advanced")
    assert fubon["basis"] == "富邦產物享樂個人海外旅行不便保險 第 21 條"
    assert tab(body, "班機延誤")["plans"][0]["recommended"] is True


def test_scenario_rules_refer_to_seeded_plans_and_benefits() -> None:
    seeded = {(b["plan_code"], b["name"]) for b in read_plan_data()["benefits"]}
    rules = load_scenario_rules()
    assert rules
    for plan_code, items in rules.items():
        for name, rule in items.items():
            assert (plan_code, name) in seeded, (plan_code, name)
            assert rule.start_hours > 0 and rule.every_hours > 0 and rule.amount > 0
