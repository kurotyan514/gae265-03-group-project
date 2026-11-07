"""1-3 推薦方案與比較表（spec #61、ADR-0021）：存在比較紀錄、讀取時重算卡片、理由與比較表。"""

import re
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from app.api.deps import current_user
from app.domain.benefits import (
    CATEGORY_CONCERN,
    CONCERN_BENEFITS,
    EXPLANATIONS,
    EXTRA_ROW_LABELS,
)
from app.domain.plans import load_plans
from app.ingest.plan_matrix import read_plan_data
from app.main import app
from app.models import Comparison, PlanPremium, User
from app.seed import load_plan_data
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

TODAY = datetime.now(ZoneInfo("Asia/Taipei")).date()


def trip(days: int, concerns: list[str], **overrides: object) -> dict:
    depart = TODAY + timedelta(days=1)
    return {
        "destination": "日本",
        "depart_date": depart.isoformat(),
        "return_date": (depart + timedelta(days=days - 1)).isoformat(),
        "age": 30,
        "concerns": concerns,
    } | overrides


@pytest.fixture
async def user(session: AsyncSession) -> AsyncGenerator[User]:
    u = User(email="a@example.com")
    session.add(u)
    await session.commit()
    app.dependency_overrides[current_user] = lambda: u
    yield u
    app.dependency_overrides.pop(current_user, None)


@pytest.fixture
async def seed(session: AsyncSession) -> None:
    await load_plan_data(session, read_plan_data())


async def create(client: AsyncClient, days: int, concerns: list[str]) -> dict:
    r = await client.post("/comparisons", json=trip(days, concerns))
    assert r.status_code == 201, r.text
    return r.json()


def picked(body: dict) -> tuple:
    rec = body["recommendation"]
    return tuple(
        (rec[k]["plan_code"], rec[k]["sum_insured"], rec[k]["premium"])
        for k in ("recommended", "alternative")
    )


@pytest.mark.usefixtures("user", "seed")
@pytest.mark.parametrize(
    ("days", "concerns", "expected", "reason"),
    [
        (
            6,
            ["班機延誤", "突然生病就醫"],
            (("fubon_advanced", 6_000_000, 985), ("huanan_basic", 3_000_000, 429)),
            "你最在意「班機延誤」，推薦方案在這一項是 9,000 元，次推薦是 6,000 元；保費多 556 元。",
        ),
        (
            6,
            ["突然生病就醫", "班機延誤"],
            (("fubon_advanced", 6_000_000, 985), ("fubon_basic", 6_000_000, 785)),
            "你最在意的「突然生病就醫」兩個方案一樣是 537,600 元；"
            "再看第 2 在意的「班機延誤」，推薦方案 9,000 元、次推薦 2,000 元；保費多 200 元。",
        ),
        (
            6,
            ["行程取消或更改"],
            (("chubb_advanced", 2_000_000, 611), ("huanan_basic", 3_000_000, 429)),
            "你最在意「行程取消或更改」，推薦方案在這一項是 320,000 元，"
            "次推薦是 50,000 元；保費多 182 元。",
        ),
    ],
)
async def test_recommendation_follows_concern_order(
    client: AsyncClient, days: int, concerns: list[str], expected: tuple, reason: str
) -> None:
    body = await create(client, days, concerns)
    assert picked(body) == expected
    assert body["recommendation"]["reason"] == reason
    # 同樣輸入兩次結果相同；GET 讀回一樣
    again = await create(client, days, concerns)
    assert again["recommendation"] == body["recommendation"]
    read = await client.get(f"/comparisons/{body['id']}")
    assert read.json() == body


@pytest.mark.usefixtures("user", "seed")
async def test_four_days_card_fraud_first(
    client: AsyncClient, session: AsyncSession
) -> None:
    body = await create(client, 4, ["信用卡盜刷", "突然生病就醫", "行程取消或更改"])
    assert picked(body) == (
        ("chubb_advanced", 2_000_000, 491),
        ("huanan_basic", 3_000_000, 358),
    )
    rec = body["recommendation"]
    assert rec["basis"] == [
        "信用卡盜刷：推薦方案較高（30,000 元 vs 20,000 元）",
        "突然生病就醫：次推薦較高（107,000 元 vs 264,000 元）",
        "行程取消或更改：推薦方案較高（320,000 元 vs 50,000 元）",
        "保費：推薦方案較高（491 元 vs 358 元）",
    ]
    card = rec["recommended"]
    assert [a["concern"] for a in card["concern_amounts"]] == [
        "信用卡盜刷",
        "突然生病就醫",
        "行程取消或更改",
    ]
    assert card["sum_insured_options"] == sorted(card["sum_insured_options"])
    assert card["recommended_sum_insured"] == card["sum_insured_options"][0]
    assert card["url"] == "https://www.einsure.com.tw/product/travel"
    assert (card["name"], card["company"]) == ("安達國外旅平險-進階型", "安達產物")

    # 存下的 4 個欄位與回傳一致
    stored = (
        await session.exec(select(Comparison).where(Comparison.id == body["id"]))
    ).one()
    assert (stored.recommended_plan_code, stored.recommended_sum_insured) == (
        "chubb_advanced",
        2_000_000,
    )
    assert (stored.alternative_plan_code, stored.alternative_sum_insured) == (
        "huanan_basic",
        3_000_000,
    )

    # 比較表：在意的列依在意事項順序在前，接著是身故；選了信用卡盜刷才有那一列
    table = rec["table"]
    assert [r["key"] for r in table] == [
        "card_fraud",
        "illness",
        "trip_cancellation",
        "death",
        "accident_medical",
        "flight_delay",
        "baggage_delay",
        "baggage_loss",
        "liability",
    ]
    assert [r["concern"] for r in table[:3]] == [
        "信用卡盜刷",
        "突然生病就醫",
        "行程取消或更改",
    ]
    assert all(r["concern"] is None for r in table[3:])  # 意外醫療不標「你在意」
    assert table[3]["recommended"] == [{"name": "身故失能保險金", "amount": 2_000_000}]
    # 海外突發疾病醫療合併一列，分別列出住院、門診、急診
    illness = table[1]
    assert illness["label"] == "海外突發疾病醫療"
    assert [i["name"] for i in illness["recommended"]] == [
        "海外突發疾病住院醫療",
        "海外突發疾病門診醫療",
        "海外突發疾病急診醫療",
    ]
    assert all(r["explanation"] for r in table)


async def premium_of(session: AsyncSession, plan: str, sum_insured: int, days: int):
    return (
        await session.exec(
            select(PlanPremium.premium).where(
                PlanPremium.plan_code == plan,
                PlanPremium.sum_insured == sum_insured,
                PlanPremium.days == days,
            )
        )
    ).one()


@pytest.mark.usefixtures("user", "seed")
async def test_changing_a_card_sum_changes_only_that_card(
    client: AsyncClient, session: AsyncSession
) -> None:
    body = await create(client, 6, ["班機延誤", "突然生病就醫"])
    before = body["recommendation"]
    alt = before["alternative"]
    new_sum = alt["sum_insured_options"][-1]

    r = await client.patch(
        f"/comparisons/{body['id']}", json={"alternative_sum_insured": new_sum}
    )
    assert r.status_code == 200, r.text
    after = r.json()["recommendation"]
    assert after["recommended"] == before["recommended"]
    assert after["reason"] == before["reason"]
    assert after["basis"] == before["basis"]
    assert after["alternative"]["plan_code"] == alt["plan_code"]
    assert after["alternative"]["sum_insured"] == new_sum
    assert after["alternative"]["recommended_sum_insured"] == 3_000_000
    assert after["alternative"]["premium"] == await premium_of(
        session, alt["plan_code"], new_sum, 6
    )
    for b, a in zip(before["table"], after["table"], strict=True):
        assert a["recommended"] == b["recommended"]
    death = next(r for r in after["table"] if r["key"] == "death")
    assert death["alternative"] == [{"name": "身故失能保險金", "amount": new_sum}]
    # 重新讀取還是改過的保額
    assert (await client.get(f"/comparisons/{body['id']}")).json()[
        "recommendation"
    ] == after

    r = await client.patch(
        f"/comparisons/{body['id']}", json={"recommended_sum_insured": 2_000_000}
    )
    assert r.status_code == 422
    assert "這個方案沒有 200 萬的報價" in r.text


@pytest.mark.usefixtures("user", "seed")
async def test_changing_sum_without_recommendation_is_rejected(
    client: AsyncClient,
) -> None:
    body = await create(client, 6, [])
    assert body["recommendation"] is None
    r = await client.patch(
        f"/comparisons/{body['id']}", json={"recommended_sum_insured": 3_000_000}
    )
    assert r.status_code == 422


@pytest.mark.usefixtures("user", "seed")
async def test_when_recommendation_is_recomputed(
    client: AsyncClient, session: AsyncSession
) -> None:
    body = await create(client, 6, ["班機延誤", "突然生病就醫"])
    url = f"/comparisons/{body['id']}"
    await client.patch(url, json={"alternative_sum_insured": 10_000_000})

    # 只改補充說明、目的地、年齡：推薦與已選保額不變
    r = await client.patch(
        url, json={"note": "會去滑雪", "age": 50, "destination": "韓國"}
    )
    assert r.json()["recommendation"]["alternative"]["sum_insured"] == 10_000_000

    # 改在意事項：重新推薦，保額回到推薦保額；同一請求的保額被忽略
    r = await client.patch(
        url,
        json={
            "concerns": ["突然生病就醫", "班機延誤"],
            "alternative_sum_insured": 10_000_000,
        },
    )
    rec = r.json()["recommendation"]
    assert rec["alternative"]["plan_code"] == "fubon_basic"
    assert rec["alternative"]["sum_insured"] == 6_000_000

    # 改天數：重新推薦
    await client.patch(url, json={"alternative_sum_insured": 10_000_000})
    depart = TODAY + timedelta(days=1)
    r = await client.patch(
        url, json={"return_date": (depart + timedelta(days=3)).isoformat()}
    )
    assert r.json()["recommendation"]["alternative"]["sum_insured"] == 6_000_000
    assert r.json()["recommendation"]["recommended"]["premium"] == await premium_of(
        session, "fubon_advanced", 6_000_000, 4
    )

    # 在意事項改成空的：清空推薦
    r = await client.patch(url, json={"concerns": []})
    assert r.json()["recommendation"] is None
    stored = (
        await session.exec(select(Comparison).where(Comparison.id == body["id"]))
    ).one()
    assert (
        stored.recommended_plan_code,
        stored.recommended_sum_insured,
        stored.alternative_plan_code,
        stored.alternative_sum_insured,
    ) == (None, None, None, None)


@pytest.mark.usefixtures("user", "seed")
async def test_without_document_or_card_concerns_there_are_no_such_rows(
    client: AsyncClient,
) -> None:
    body = await create(client, 6, ["行程取消或更改"])
    table = body["recommendation"]["table"]
    keys = [r["key"] for r in table]
    assert "document_loss" not in keys
    assert "card_fraud" not in keys
    assert keys[:2] == ["trip_cancellation", "death"]
    # 華南基礎型沒有旅程更改的法定傳染病，安達進階型四項都有
    trip_row = table[0]
    assert len(trip_row["recommended"]) == 4
    assert len(trip_row["alternative"]) == 2


def tiny_plan_data() -> dict:
    """兩個方案、5 天：行李延誤額度相同；班機延誤是貴的那個（泰安）比較少。"""

    def plan(code: str, premium: int, flight: int) -> tuple[dict, list[dict]]:
        benefits = [
            ("身故失能保險金", None, 2_000_000),
            ("班機延誤保險(定額給付-累進式)", "班機延誤", flight),
            ("行李延誤保險(定額給付)", "行李延誤", 500),
        ]
        return (
            {
                "plan_code": code,
                "sum_insured": 2_000_000,
                "days": 5,
                "premium": premium,
            },
            [
                {
                    "plan_code": code,
                    "sum_insured": 2_000_000,
                    "name": n,
                    "category": c,
                    "amount": a,
                    "position": i,
                }
                for i, (n, c, a) in enumerate(benefits)
            ],
        )

    (p1, b1), (p2, b2) = plan("taian", 100, 2000), plan("chubb_basic", 200, 1000)
    return {"premiums": [p1, p2], "benefits": b1 + b2}


@pytest.mark.usefixtures("user")
async def test_equal_amounts_and_cheaper_recommendation(
    client: AsyncClient, session: AsyncSession
) -> None:
    await load_plan_data(session, tiny_plan_data())

    same = await create(client, 5, ["行李延誤"])
    assert same["recommendation"]["reason"] == (
        "你在意的項目兩個方案額度相同，推薦方案保費少 100 元。"
    )
    assert same["recommendation"]["basis"] == [
        "行李延誤：兩者相同（500 元 vs 500 元）",
        "保費：推薦方案較低（100 元 vs 200 元）",
    ]

    cheaper = await create(client, 5, ["班機延誤"])
    assert picked(cheaper) == (
        ("taian", 2_000_000, 100),
        ("chubb_basic", 2_000_000, 200),
    )
    assert cheaper["recommendation"]["reason"] == (
        "你最在意「班機延誤」，推薦方案在這一項是 2,000 元，次推薦是 1,000 元；保費還少 100 元。"
    )
    # 沒有的保障是空清單（前端顯示「未列」）
    medical = next(
        r for r in cheaper["recommendation"]["table"] if r["key"] == "accident_medical"
    )
    assert medical["recommended"] == medical["alternative"] == []


@pytest.mark.usefixtures("user", "seed")
async def test_emergency_row_is_added_and_marked_when_chosen(
    client: AsyncClient,
) -> None:
    body = await create(client, 6, ["需要緊急送醫或家屬趕來", "班機延誤"])
    table = body["recommendation"]["table"]
    emergency = table[0]
    assert (emergency["key"], emergency["label"]) == ("emergency", "緊急救援")
    assert emergency["concern"] == "需要緊急送醫或家屬趕來"
    assert not re.search(r"\d", emergency["explanation"])
    # 富邦進階（緊急救援費用）與臺產進階（緊急處理費用）同分，各自列出自己的項目
    assert body["recommendation"]["recommended"]["plan_code"] == "fubon_advanced"
    assert emergency["recommended"] == [{"name": "緊急救援費用", "amount": 1_000_000}]
    assert emergency["alternative"] == [{"name": "緊急處理費用", "amount": 1_000_000}]
    # 沒選就沒有這一列
    other = await create(client, 6, ["班機延誤"])
    assert "emergency" not in [r["key"] for r in other["recommendation"]["table"]]


@pytest.mark.usefixtures("user", "seed")
async def test_liability_row_leaves_out_home_third_party_liability(
    client: AsyncClient,
) -> None:
    # 緊急送醫排第 1：臺產進階（旅遊責任與住居所第三人責任兩項）是次推薦，富邦進階是推薦
    body = await create(
        client, 6, ["需要緊急送醫或家屬趕來", "不小心弄傷別人或弄壞東西"]
    )
    rec = body["recommendation"]
    assert rec["alternative"]["plan_code"] == "tfmi_advanced"
    row = next(r for r in rec["table"] if r["key"] == "liability")
    assert row["concern"] == "不小心弄傷別人或弄壞東西"
    assert [i["name"] for i in row["alternative"]] == ["旅遊責任保險(無自負額)"]


def test_every_plan_has_url() -> None:
    assert all(p.url.startswith("https://") for p in load_plans())


def test_concern_benefits_fall_in_their_category_rows() -> None:
    for b in read_plan_data()["benefits"]:
        for concern, names in CONCERN_BENEFITS.items():
            if b["name"] in names:
                if concern in EXTRA_ROW_LABELS:
                    assert b["category"] is None, b
                else:
                    assert CATEGORY_CONCERN[b["category"]] == concern, b


def test_explanations_have_no_numbers() -> None:
    assert {"海外突發疾病醫療", "緊急救援"} <= set(EXPLANATIONS)
    for text in EXPLANATIONS.values():
        assert not re.search(r"\d", text), text


@pytest.mark.usefixtures("user", "seed")
async def test_emergency_first_ties_two_advanced_plans_and_second_concern_decides(
    client: AsyncClient,
) -> None:
    # 臺產進階（緊急處理費用）與富邦進階（緊急救援費用）都是 1,000,000 元，同分
    for second in ("班機延誤", "突然生病就醫"):
        body = await create(client, 6, ["需要緊急送醫或家屬趕來", second])
        card = body["recommendation"]["recommended"]
        assert card["plan_code"] == "fubon_advanced"
        assert card["concern_amounts"][0]["amount"] == 1_000_000
        alt = body["recommendation"]["alternative"]
        assert alt["plan_code"] == "tfmi_advanced"
        assert alt["concern_amounts"][0]["amount"] == 1_000_000
    # 第 2 項沒有分出高下時，同分取保費最低
    only = await create(client, 6, ["需要緊急送醫或家屬趕來"])
    assert picked(only)[0][0] == "tfmi_advanced"


@pytest.mark.usefixtures("user", "seed")
@pytest.mark.parametrize("second", ["班機延誤", "行李延誤", "突然生病就醫"])
async def test_liability_first_recommends_chubb_advanced(
    client: AsyncClient, second: str
) -> None:
    body = await create(client, 6, ["不小心弄傷別人或弄壞東西", second])
    assert picked(body)[0][0] == "chubb_advanced"
