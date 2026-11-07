"""1-4 情境試算（spec #120、#147）：GET /comparisons/{id}/scenarios，數字全由程式依 plan_benefit 與給付規則算出。"""

from collections.abc import AsyncGenerator, Iterator
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from app.api.deps import current_user
from app.domain.benefits import EXPLANATIONS, EXTRA_ROW_LABELS, ILLNESS_LABEL, Concern
from app.domain.scenarios import PayoutRule, load_scenario_rules
from app.ingest.plan_matrix import read_plan_data
from app.main import app
from app.models import User
from app.seed import SEED_PATH, load_plan_data, load_seed, read_seed
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

TODAY = datetime.now(ZoneInfo("Asia/Taipei")).date()
FLIGHT = "班機延誤保險(定額給付-累進式)"
BAGGAGE_DELAY = "行李延誤保險(定額給付)"
SICK = "海外突發疾病住院醫療(乙型)"
TABS = ["航班延誤", "生病住院", "行前取消", "錢包被偷", "騎車撞傷"]
NOTE = "背包視為「類似容器」，包內物品可依損失申請，背包本身不賠。"


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
    """兩個方案、5 天。泰安：班機延誤 6,000、行李損失 2,000、旅行文件損失 1,000、
    海外疾病住院 3%、傷害醫療隨身故保額變，沒有信用卡盜用、緊急救援、責任保險；
    安達基礎型：班機延誤 3,000，其餘都沒有。行李延誤同額，所以在意班機延誤時推薦泰安。"""
    plans = {
        "taian": {
            2_000_000: (
                100,
                {
                    FLIGHT: 6000,
                    "行李損失保險(定額給付)": 2000,
                    "旅行文件損失保險(定額給付)": 1000,
                },
            ),
            3_000_000: (
                150,
                {
                    FLIGHT: 6000,
                    "行李損失保險(定額給付)": 2000,
                    "旅行文件損失保險(定額給付)": 1000,
                },
            ),
        },
        "chubb_basic": {2_000_000: (200, {FLIGHT: 3000})},
    }
    category = {
        FLIGHT: "班機延誤",
        BAGGAGE_DELAY: "行李延誤",
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
                BAGGAGE_DELAY: 500,
                "傷害醫療費用保險": sum_insured // 10,
            } | extra
            if code == "taian":
                items[SICK] = sum_insured * 3 // 100
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


def tab(body: list[dict], name: str) -> dict:
    return next(s for s in body if s["tab"] == name)


def row(body: list[dict], tab_name: str, row_name: str) -> dict:
    return next(r for r in tab(body, tab_name)["rows"] if r["name"] == row_name)


def col_of(body: list[dict], tab_name: str, row_name: str, plan_code: str) -> dict:
    return next(
        p for p in row(body, tab_name, row_name)["plans"] if p["plan_code"] == plan_code
    )


@pytest.mark.usefixtures("user", "tiny", "rules")
async def test_always_five_tabs_starred_first_in_concern_order(
    client: AsyncClient,
) -> None:
    # #147 的例子：選 1 突然生病就醫、2 不小心弄傷別人
    body = await scenarios(
        client,
        await create(client, 5, ["突然生病就醫", "不小心弄傷別人或弄壞東西"]),
    )
    assert [(s["tab"], s["starred"]) for s in body] == [
        ("生病住院", True),
        ("騎車撞傷", True),
        ("航班延誤", False),
        ("行前取消", False),
        ("錢包被偷", False),
    ]
    assert tab(body, "騎車撞傷")["concerns"] == [
        "需要緊急送醫或家屬趕來",
        "不小心弄傷別人或弄壞東西",
    ]

    # 排名依涵蓋的在意事項中最前面的那個：弄傷別人排第 1，騎車撞傷就在航班延誤前面
    body = await scenarios(
        client, await create(client, 5, ["不小心弄傷別人或弄壞東西", "班機延誤"])
    )
    assert [(s["tab"], s["starred"]) for s in body] == [
        ("騎車撞傷", True),
        ("航班延誤", True),
        ("生病住院", False),
        ("行前取消", False),
        ("錢包被偷", False),
    ]

    # 沒有任何情境涵蓋的在意事項時，照表的順序、沒有 ★
    body = await scenarios(client, await create(client, 5, ["證件遺失"]))
    assert [(s["tab"], s["starred"]) for s in body] == [
        ("錢包被偷", True),
        ("航班延誤", False),
        ("生病住院", False),
        ("行前取消", False),
        ("騎車撞傷", False),
    ]


@pytest.mark.usefixtures("user", "tiny", "rules")
async def test_bike_crash_is_starred_only_by_emergency_or_liability(
    client: AsyncClient,
) -> None:
    # 意外傷害醫療不屬於任何在意事項，選了生病就醫也不會讓騎車撞傷加 ★
    body = await scenarios(client, await create(client, 5, ["突然生病就醫"]))
    assert tab(body, "騎車撞傷")["starred"] is False
    body = await scenarios(client, await create(client, 5, ["需要緊急送醫或家屬趕來"]))
    assert tab(body, "騎車撞傷")["starred"] is True


@pytest.mark.usefixtures("user", "tiny", "rules")
async def test_wallet_has_three_rows_a_note_and_not_covered_cells(
    client: AsyncClient,
) -> None:
    body = await scenarios(client, await create(client, 5, ["班機延誤"]))
    wallet = tab(body, "錢包被偷")
    assert wallet["note"] == NOTE
    assert [(r["name"], r["method"]) for r in wallet["rows"]] == [
        ("行李損失", "實支實付"),
        ("旅行文件損失", "實支實付"),
        ("信用卡盜用", "實支實付"),
    ]
    assert [s["tab"] for s in body if s["note"]] == ["錢包被偷"]

    loss = col_of(body, "錢包被偷", "行李損失", "taian")
    assert loss | {"basis": None} == {
        "plan_code": "taian",
        "name": "泰安國外旅平險",
        "company": "泰安產物",
        "recommended": True,
        "result": "在保障範圍內",
        "benefit": "行李損失保險(定額給付)",
        "max_amount": 2000,
        "payout": None,
        "outcome": "依實際收據，最高 2,000 元",
        "basis": None,
    }
    # 泰安沒有信用卡盜用、安達基礎型什麼都沒有：不在保障範圍，其餘欄位是 null
    for plan_code, row_name in [
        ("taian", "信用卡盜用"),
        ("chubb_basic", "行李損失"),
        ("chubb_basic", "旅行文件損失"),
    ]:
        cell = col_of(body, "錢包被偷", row_name, plan_code)
        assert cell["result"] == "不在保障範圍"
        head = {"plan_code", "name", "company", "recommended", "result"}
        assert {v for k, v in cell.items() if k not in head} == {None}
    assert wallet["conclusion"] == (
        "泰安國外旅平險：行李損失 依實際收據，最高 2,000 元、"
        "旅行文件損失 依實際收據，最高 1,000 元、信用卡盜用 不在保障範圍；"
        "安達國外旅平險-基礎型：行李損失 不在保障範圍、"
        "旅行文件損失 不在保障範圍、信用卡盜用 不在保障範圍。"
    )


@pytest.mark.usefixtures("user", "tiny", "rules")
async def test_rows_carry_explanations_for_name_and_method(client: AsyncClient) -> None:
    body = await scenarios(client, await create(client, 5, ["班機延誤"]))
    for s in body:
        for r in s["rows"]:
            assert r["name_explanation"], r["name"]
            assert r["method"] in {"定額", "實支實付"}
            assert r["method_explanation"], r["name"]
    assert [r["name"] for r in tab(body, "航班延誤")["rows"]] == [
        "班機延誤",
        "行李延誤",
    ]
    # 與 1-3 比較表同名的列，名稱與名詞解釋跟比較表一致（只有一份文字）
    for scenario, label in [
        ("生病住院", ILLNESS_LABEL),
        ("騎車撞傷", EXTRA_ROW_LABELS[Concern.EMERGENCY]),
    ]:
        same = next(r for r in tab(body, scenario)["rows"] if r["name"] == label)
        assert same["name_explanation"] == EXPLANATIONS[label]
    assert tab(body, "航班延誤")["assumption"] == "班機延誤 8 小時；行李延誤 20 小時"
    assert tab(body, "航班延誤")["story"].startswith("颱風來了，出國的班機延誤 8 小時")
    # 欄是清單：推薦在前、次推薦在後
    assert [
        (p["plan_code"], p["recommended"])
        for p in row(body, "航班延誤", "班機延誤")["plans"]
    ] == [("taian", True), ("chubb_basic", False)]


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


@pytest.mark.usefixtures("user", "tiny")
async def test_fixed_payout_follows_rule_and_cap(
    client: AsyncClient, rules: dict[str, dict[str, PayoutRule]]
) -> None:
    cid = await create(client, 5, ["班機延誤"])
    # 8 小時、起賠 4、每滿 4 小時 2,000：泰安上限 6,000 → 4,000；安達上限 3,000 → 3,000
    rules["taian"] = {FLIGHT: PayoutRule(4, 4, 2000)}
    rules["chubb_basic"] = {FLIGHT: PayoutRule(4, 4, 2000)}
    body = await scenarios(client, cid)
    taian = col_of(body, "航班延誤", "班機延誤", "taian")
    assert taian | {"basis": None} == {
        "plan_code": "taian",
        "name": "泰安國外旅平險",
        "company": "泰安產物",
        "recommended": True,
        "result": "在保障範圍內",
        "benefit": FLIGHT,
        "max_amount": 6000,
        "payout": 4000,
        "outcome": "4,000 元",
        "basis": None,
    }
    chubb = col_of(body, "航班延誤", "班機延誤", "chubb_basic")
    assert (chubb["payout"], chubb["max_amount"]) == (3000, 3000)

    # 起賠 10 小時：0 元、未達給付條件
    rules["taian"] = {FLIGHT: PayoutRule(10, 4, 2000)}
    taian = col_of(await scenarios(client, cid), "航班延誤", "班機延誤", "taian")
    assert (taian["result"], taian["payout"], taian["outcome"]) == (
        "在保障範圍內，但本情境未達給付條件",
        0,
        "0 元",
    )


@pytest.mark.usefixtures("user", "tiny")
async def test_rule_max_amount_and_one_time_payout_and_conclusion(
    client: AsyncClient, rules: dict[str, dict[str, PayoutRule]]
) -> None:
    cid = await create(client, 5, ["班機延誤"])
    # 試算表額度是每滿 4 小時的金額：每次最高由規則決定，8 小時 → 2 次 × 6,000
    rules["taian"] = {
        FLIGHT: PayoutRule(4, 4, 6000, 12000),
        BAGGAGE_DELAY: PayoutRule(6, None, 500),
    }
    body = await scenarios(client, cid)
    flight = col_of(body, "航班延誤", "班機延誤", "taian")
    assert (flight["payout"], flight["max_amount"]) == (12000, 12000)
    # 一次定額：20 小時也只賠一次
    bag = col_of(body, "航班延誤", "行李延誤", "taian")
    assert (bag["payout"], bag["max_amount"]) == (500, 500)
    # 結論句由程式把各列串起來：有規則算金額，沒有規則只顯示上限
    assert tab(body, "航班延誤")["conclusion"] == (
        "泰安國外旅平險：班機延誤 賠 12,000 元、行李延誤 賠 500 元；"
        "安達國外旅平險-基礎型：班機延誤 依延誤時數計算，最高 3,000 元、"
        "行李延誤 依延誤時數計算，最高 500 元。"
    )


@pytest.mark.usefixtures("user", "tiny", "rules")
async def test_fixed_without_rule_shows_only_the_cap(client: AsyncClient) -> None:
    body = await scenarios(client, await create(client, 5, ["班機延誤"]))
    chubb = col_of(body, "航班延誤", "班機延誤", "chubb_basic")
    assert (chubb["result"], chubb["payout"], chubb["outcome"]) == (
        "在保障範圍內",
        None,
        "依延誤時數計算，最高 3,000 元",
    )


@pytest.mark.usefixtures("user", "tiny", "rules")
async def test_reimbursement_shows_receipt_cap_and_missing_benefit(
    client: AsyncClient,
) -> None:
    body = await scenarios(client, await create(client, 5, ["班機延誤"]))
    sick = col_of(body, "生病住院", "海外突發疾病醫療", "taian")
    assert (sick["benefit"], sick["max_amount"], sick["outcome"]) == (
        SICK,
        60_000,
        "依實際收據，最高 60,000 元",
    )
    assert sick["payout"] is None
    # 方案沒有該保障：試算結果「不在保障範圍」
    cancel = col_of(body, "行前取消", "旅程取消", "taian")
    assert cancel["result"] == "不在保障範圍"
    assert cancel["benefit"] is None and cancel["max_amount"] is None
    # 意外傷害醫療的額度隨身故保額變
    accident = col_of(body, "騎車撞傷", "意外傷害醫療", "taian")
    assert accident["max_amount"] == 200_000


@pytest.mark.usefixtures("user", "tiny", "rules")
async def test_max_amount_follows_card_sum_insured(client: AsyncClient) -> None:
    cid = await create(client, 5, ["班機延誤"])
    r = await client.patch(
        f"/comparisons/{cid}", json={"recommended_sum_insured": 3_000_000}
    )
    assert r.status_code == 200, r.text
    sick = col_of(await scenarios(client, cid), "生病住院", "海外突發疾病醫療", "taian")
    assert (sick["max_amount"], sick["outcome"]) == (
        90_000,
        "依實際收據，最高 90,000 元",
    )


@pytest.fixture
async def real_data(session: AsyncSession) -> None:
    await load_plan_data(session, read_plan_data())
    # 條文與險種用真實 seed；向量用不到，不載入
    await load_seed(session, read_seed(SEED_PATH) | {"embeddings": []})


@pytest.mark.usefixtures("user", "real_data")
async def test_flight_delay_uses_scenario_rules_json_and_basis_points_to_article(
    client: AsyncClient,
) -> None:
    # 不換掉給付規則：用 scenario_rules.json。6 天、在意班機延誤：推薦富邦進階型
    body = await scenarios(
        client, await create(client, 6, ["班機延誤", "突然生病就醫"])
    )
    assert tab(body, "航班延誤")["starred"] is True
    flight = col_of(body, "航班延誤", "班機延誤", "fubon_advanced")
    # 起賠 4 小時、每滿 4 小時 6,000、每次最高 12,000：8 小時 → 2 次 = 12,000
    assert (flight["payout"], flight["max_amount"]) == (12_000, 12_000)
    # 行李延誤：滿 6 小時定額 6,000，20 小時也只賠一次
    bag = col_of(body, "航班延誤", "行李延誤", "fubon_advanced")
    assert (bag["payout"], bag["max_amount"]) == (6_000, 6_000)
    assert flight["basis"] == "富邦產物享樂個人海外旅行不便保險 第 21 條"
    assert tab(body, "航班延誤")["conclusion"].startswith(
        "富邦國外旅平險-進階型：班機延誤 賠 12,000 元、行李延誤 賠 6,000 元；"
    )
    # 真實資料：方案沒有的保障不是錯誤，給付方式只有定額或實支實付
    for s in body:
        assert {r["method"] for r in s["rows"]} <= {"定額", "實支實付"}
    # 騎車撞傷：富邦進階有緊急救援與責任保險，華南基礎有家屬看護與責任保險
    crash = tab(body, "騎車撞傷")
    assert [r["name"] for r in crash["rows"]] == [
        "意外傷害醫療",
        "緊急救援",
        "責任保險",
    ]
    assert col_of(body, "騎車撞傷", "緊急救援", "fubon_advanced")["max_amount"] == (
        1_000_000
    )


def test_scenario_rules_refer_to_seeded_plans_and_benefits() -> None:
    seeded = {(b["plan_code"], b["name"]) for b in read_plan_data()["benefits"]}
    rules = load_scenario_rules()
    for plan_code, items in rules.items():
        for name, rule in items.items():
            assert (plan_code, name) in seeded, (plan_code, name)
            assert rule.start_hours > 0 and rule.amount > 0
            assert rule.every_hours is None or rule.every_hours > 0
            assert rule.max_amount is None or rule.max_amount >= rule.amount
